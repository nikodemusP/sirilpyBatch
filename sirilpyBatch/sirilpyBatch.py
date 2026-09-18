"""
sirilpyBatch - a Siril PyQt6 batch-processing front end.

Lets the user drag-and-drop plugins from a sidebar list into an ordered
batch, configure each one through its own widget box, reorder/remove them,
and run the batch against a running Siril instance. Batch composition and
per-plugin settings are persisted to YAML so a project can be reopened later.

Key building blocks:
    BatchConfig          - reads/writes the YAML config & presets files.
    BatchContext         - shared (siril, config) handle passed to plugins.
    PluginItem           - declarative description of one config widget.
    PluginConfigBox      - renders a plugin's PluginItem list + Load/Process buttons.
    BatchPlugin          - base class plugin authors subclass.
    BatchPluginRegistry  - collects plugins registered via @register(...).
    PluginContainer      - the drop target holding the ordered, active plugins.
    PluginList           - the draggable sidebar list of available plugins.
    Batch                - the main window tying everything together.
"""

from dataclasses import dataclass, field
import importlib.util
import os
import pathlib
import sys
from pathlib import Path
from typing import Any, Optional, Type

import yaml
import sirilpy as s
from sirilpy import LogColor

from PyQt6.QtCore import QMimeData, Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QDrag
from PyQt6.QtWidgets import (
    QApplication,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QSizePolicy,
    QSlider,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QCheckBox,
    QDoubleSpinBox,
    QComboBox,
    QGroupBox,
    QSpinBox,
    QScrollArea,
)

APP_NAME = "sirilpyBatch"
VERSION = "0.1.0"


# ------------------------------------------------------------------------------------------
class BatchConfig:
    """
    Reads and writes the plugin's on-disk configuration.

    Two separate files are involved:
      * ``config.yaml``               - per-project settings, stored in the current
                                         Siril working directory (created on first use).
      * ``origin_m2_presets.yaml``    - user-wide presets, stored in Siril's user data
                                         directory so they survive across projects.
    """

    def __init__(self, siril):
        self.siril = siril
        config_dir = Path(siril.get_siril_userdatadir())
        config_dir.mkdir(parents=True, exist_ok=True)
        self.presets_file = config_dir / "sirilpyBatch.yaml"

    def readPresetConfig(self):
        """Load the user-wide presets file, or None if it doesn't exist yet / fails to parse."""
        self.siril.log(f"read preset config", LogColor.GREEN)
        if not self.presets_file.exists():
            self.siril.log("Presets file not found: sirilpyBatch.yaml", LogColor.RED)
            return None
        try:
            with open(self.presets_file, "r") as f:
                presets = yaml.safe_load(f)
                self.siril.log("Presets loaded successfully.", LogColor.GREEN)
                return presets
        except Exception as e:
            self.siril.log(f"Error reading presets file: {str(e)}", LogColor.RED)
            return None

    def storePresets(self, config):
        """Persist the user-wide presets dict to ``sirilpyBatch.yaml``."""
        try:
            with open(self.presets_file, "w") as f:
                yaml.safe_dump(config, f)
                self.siril.log("Configuration saved successfully.", LogColor.GREEN)
        except Exception as e:
            self.siril.log(f"Error saving configuration file: {str(e)}", LogColor.RED)


# ------------------------------------------------------------------------------------------
@dataclass
class BatchContext:
    """
    Shared, read-only-ish handle passed to every plugin instance.

    Bundles the live Siril connection (``siril``) together with the project's
    persisted configuration dict (``config``), so plugins never need to know
    where either of those come from.
    """

    siril: Any
    config: dict


# ------------------------------------------------------------------------------------------
@dataclass
class PluginItem:
    """
    Declarative description of a single configuration control inside a plugin's box.

    A plugin describes its UI as a list of ``PluginItem`` objects; ``PluginConfigBox``
    turns each one into the matching Qt widget (see ``_create_item_widget``).
    """
    key: str  = None # internal key used to read/write this item's value
    label: str = None  # label for the widget
    labelPos: str = "LEFT"
    default: Any = None
    tooltip: str = ""
    value: Any = None
    colspan: int = 1  # how many grid columns this item's cell should occupy (e.g. for a
    # wide text field); clamped to the box's total column count and will
    # wrap to a new row if it doesn't fit in the remaining space.

@dataclass
class SeparatorItem(PluginItem):
    pass


@dataclass
class CheckboxItem(PluginItem):
    labelPos: str = "RIGHT"
    pass

@dataclass
class NumberItem(PluginItem):
    step: float = 1
    minimum: float = 0
    maximum: float = 100
    pass

@dataclass
class SliderItem(NumberItem):
    step: float = 1
    minimum: float = 0
    maximum: float = 100
    pass

@dataclass
class IntItem(NumberItem):
    pass

@dataclass
class FloatItem(NumberItem):
    decimals: int = 2  # used only by "float" items
    pass

@dataclass
class TextItem(PluginItem):
    pass

@dataclass
class ComboBoxItem(PluginItem):
    values: list[Any] = field(default_factory=list)
    
# ------------------------------------------------------------------------------------------
class PluginConfigBox(QGroupBox):
    """
    A checkable group box that renders a plugin's ``PluginItem`` list as a
    grid of labeled widgets, plus an optional "Load" and/or "Process" button.

    Signals:
        valueChanged(str, object) -> active on each value change of the contained widgets, emits (key, value)
        loadRequested()           -> "Load" button was clicked (only if has_load=True)
        processRequested()        -> "Process" button was clicked (only if has_process=True)
    """

    valueChanged = pyqtSignal(str, object)

    loadRequested = pyqtSignal()
    processRequested = pyqtSignal()

    def __init__(
        self,
        title: str,
        items: list[PluginItem],
        parent: Optional[QWidget] = None,
        has_load: bool = False,
        has_process: bool = False,
        columns: int = 5,
    ):
        super().__init__(title, parent)

        self.items = items
        self.columns = max(1, columns)

        # Maps PluginItem.key -> the live Qt widget holding that item's value.
        self.widgets: dict[str, QWidget] = {}
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        self._create_ui(has_load=has_load, has_process=has_process)

    # ------------------------------------------------------------------
    def _create_ui(self, has_load: bool, has_process: bool):
        """
        Lay out ``self.items`` in a grid with ``self.columns`` columns
        (wrapping to a new row as needed), then append the Load/Process
        button row at the bottom if requested.

        A "separator" item forces a line break and draws a thin horizontal
        rule spanning the full width of the grid.
        """
        main_layout = QVBoxLayout(self)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(
            4
        )  # keep rows close together, especially when items span full width
        # Reserve all `columns` as equal-width slots up front. Without this,
        # Qt only creates as many grid columns as actually have a widget in
        # them, so a colspan=2 item on a 3-column grid would stretch to fill
        # 100% of the width instead of the intended 2/3, whenever nothing
        # else ever lands in the 3rd column.
        for col in range(self.columns):
            grid.setColumnStretch(col, 1)

        row = 0
        column = 0

        if self.items:
            for item in self.items:
                if isinstance(item, SeparatorItem):
                    # Start the separator on its own row, even if the current
                    # row isn't full yet.
                    if column != 0:
                        row += 1
                        column = 0

                    line = QLabel()
                    line.setFixedHeight(1)

                    grid.addWidget(line, row, 0, 1, self.columns)

                    row += 1
                    continue

                widget = self._create_item_widget(item)

                if widget is None:
                    continue

                # Clamp the requested span to a sane range and wrap to a fresh
                # row first if it wouldn't fit in the remaining columns.
                span = max(1, min(item.colspan, self.columns))
                if column + span > self.columns:
                    column = 0
                    row += 1

                # Each cell is its own little "label beside widget" mini-layout.
                label = QLabel(item.label)
                if item.tooltip:
                    label.setToolTip(item.tooltip)
                    widget.setToolTip(item.tooltip)

                # Label and widget side by side on one line.
                cell = QHBoxLayout()
                cell.setContentsMargins(0, 0, 0, 0)
                cell.setSpacing(6)

                label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
                if isinstance(widget, QCheckBox):
                    widget.setSizePolicy(
                        QSizePolicy.Policy.Fixed,
                        QSizePolicy.Policy.Fixed,
                    )
                else:
                    widget.setSizePolicy(
                        QSizePolicy.Policy.Expanding,
                        QSizePolicy.Policy.Fixed,
                    )

                label_position = (item.labelPos or "LEFT").upper()
                if label_position == "RIGHT":
                    cell.addWidget(widget)
                    cell.addSpacing(4)
                    cell.addWidget(label)
                    cell.addStretch(1)
                else:
                    cell.addWidget(label)
                    cell.addWidget(widget, 1)
                    
                container = QWidget()
                container.setLayout(cell)

                grid.addWidget(container, row, column, 1, span)
                self.widgets[item.key] = widget

                # Advance past the cell(s) just used, wrapping to a new row when full.
                column += span
                if column >= self.columns:
                    column = 0
                    row += 1

            main_layout.addLayout(grid)

        # Optional footer row with Load/Process buttons, right-aligned.
        buttons = QHBoxLayout()
        buttons.addStretch()
        if has_load:
            load_button = QPushButton("Load")
            load_button.setMinimumWidth(60)
            load_button.setMinimumHeight(30)            
            load_button.clicked.connect(self.loadRequested.emit)
            buttons.addWidget(load_button)

        if has_process:
            process_button = QPushButton("Process")
            process_button.setMinimumWidth(60)
            process_button.setMinimumHeight(30)            
            process_button.clicked.connect(self.processRequested.emit)
            buttons.addWidget(process_button)

        if has_load or has_process:
            main_layout.addLayout(buttons)

    # ------------------------------------------------------------------
    def _create_item_widget(self, item: PluginItem) -> Optional[QWidget]:
        """
        Build and wire up the concrete Qt widget for one ``PluginItem``.

        Every widget's change signal is connected so it re-emits this box's
        generic ``valueChanged(key, value)`` signal, letting callers observe
        all controls uniformly without caring about the underlying widget type.
        """

        # --------------------------------------------------------------
        if isinstance(item, CheckboxItem):
            widget = QCheckBox()
            widget.setChecked(bool(item.default if item.default is not None else False))

            widget.stateChanged.connect(
                lambda state, key=item.key: self.valueChanged.emit(
                    key,
                    state == Qt.CheckState.Checked.value,
                )
            )
            return widget

        # --------------------------------------------------------------
        if isinstance(item, SliderItem):
            widget = QSlider(Qt.Orientation.Horizontal)

            widget.setMinimum(int(item.minimum))

            widget.setMaximum(int(item.maximum))

            widget.setSingleStep(int(item.step))

            value = item.default if item.default is not None else item.minimum

            widget.setValue(int(value))

            widget.valueChanged.connect(
                lambda value, key=item.key: self.valueChanged.emit(
                    key,
                    value,
                )
            )
            return widget

        # --------------------------------------------------------------
        if isinstance(item, IntItem):

            widget = QSpinBox()
            widget.setMinimum(int(item.minimum))
            widget.setMaximum(int(item.maximum))
            widget.setSingleStep(int(item.step))

            value = item.default if item.default is not None else item.minimum

            widget.setValue(int(value))

            widget.valueChanged.connect(
                lambda value, key=item.key: self.valueChanged.emit(
                    key,
                    value,
                )
            )
            return widget

        # --------------------------------------------------------------
        if isinstance(item, FloatItem):

            widget = QDoubleSpinBox()
            widget.setMinimum(float(item.minimum))

            widget.setMaximum(float(item.maximum))

            widget.setSingleStep(float(item.step))

            widget.setDecimals(int(item.decimals))

            value = item.default if item.default is not None else item.minimum

            widget.setValue(float(value))

            widget.valueChanged.connect(
                lambda value, key=item.key: self.valueChanged.emit(
                    key,
                    value,
                )
            )
            return widget

        # --------------------------------------------------------------
        if isinstance(item, TextItem):
            widget = QLineEdit()
            if item.default is not None:
                widget.setText(str(item.default))

            widget.textChanged.connect(
                lambda value, key=item.key: self.valueChanged.emit(
                    key,
                    value,
                )
            )
            return widget

        if isinstance(item, ComboBoxItem):
            widget = QComboBox()

            for value in item.values:
                widget.addItem(str(value), userData=value)

            if item.default in item.values:
                widget.setCurrentIndex(item.values.index(item.default))

            widget.currentIndexChanged.connect(
                lambda _index, key=item.key, combo=widget:
                    self.valueChanged.emit(key, combo.currentData())
            )

            return widget
        return None

    # ------------------------------------------------------------------
    def get_value(self, key: str) -> Any:
        """Read the current value of the widget registered under ``key``."""

        widget = self.widgets.get(key)
        if widget is None:
            return None

        if isinstance(widget, QCheckBox):
            return widget.isChecked()

        if isinstance(widget, QSlider):
            return widget.value()

        if isinstance(widget, QSpinBox):
            return widget.value()

        if isinstance(widget, QDoubleSpinBox):
            return widget.value()

        if isinstance(widget, QLineEdit):
            return widget.text()

        if isinstance(widget, QComboBox):
            return widget.currentData()

        return None

    # ------------------------------------------------------------------
    def get_config(self) -> dict[str, Any]:
        """Snapshot every item's current value into a plain dict (e.g. for saving to YAML)."""
        cfg: dict[str, Any] = {}
        if self.items == None:
            return cfg
        
        for item in self.items:
            if isinstance(item, SeparatorItem):
                continue
            cfg[item.key] = self.get_value(item.key)
        return cfg

    # ------------------------------------------------------------------
    def set_config(self, config: Optional[dict[str, Any]]):
        """Apply previously-saved values back onto the widgets (e.g. when loading a preset)."""
        if not config:
            return

        for item in self.items:

            if isinstance(item, SeparatorItem):
                continue

            if item.key not in config:
                continue

            value = config[item.key]
            widget = self.widgets.get(item.key)

            if widget is None:
                continue

            if isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))

            elif isinstance(widget, QSlider):
                widget.setValue(int(value))

            elif isinstance(widget, QSpinBox):
                widget.setValue(int(value))

            elif isinstance(widget, QDoubleSpinBox):
                widget.setValue(float(value))

            elif isinstance(widget, QLineEdit):
                widget.setText(str(value))

            elif isinstance(widget, QComboBox):
                index = widget.findData(value)
                if index >= 0:
                    widget.setCurrentIndex(index)
# ------------------------------------------------------------------------------------------
class BatchPlugin:
    """
    Abstract base class for all batch plugins.

    Subclasses declare their UI via ``set_Up`` (called by the registry/entry)
    and implement whichever of ``process()`` / ``load()`` they need:
      * ``process()`` runs the plugin's main batch action.
      * ``load()`` runs a lighter "preview/load only" action.
    Whether the "Process" and/or "Load" buttons are shown is decided
    automatically in ``create_plugin_box`` based on which of these methods
    a subclass actually overrides.
    """

    def __init__(self, siril: Any, config: dict ):
        self.context = BatchContext(
            siril=siril,
            config=config if isinstance(config, dict) else {},
        )

    def set_up(self, key: str, title: str, items: PluginItem, columns: int = 5):
        """Called once after construction to bind this instance to its registry entry."""
        self.plugin_items = items
        self.key_name = key
        self.title = title
        self.columns = columns
        self.context.siril.log(f"setup plugin: {self.title}", LogColor.GREEN)

    def create_plugin_box(self):
        """
        Build the ``PluginConfigBox`` widget for this plugin.

        Detects whether the subclass overrides ``process``/``load`` (versus
        inheriting the no-op default) to decide which action buttons to show,
        and wires those buttons to ``_on_process``/``_on_load``.
        """
        has_process = type(self).process is not BatchPlugin.process
        has_load = type(self).load is not BatchPlugin.load

        self.box = PluginConfigBox(
            self.title,
            self.plugin_items,
            has_load=has_load,
            has_process=has_process,
            columns=self.columns,
        )

        if has_process:
            self.box.processRequested.connect(self._on_process)
        if has_load:
            self.box.loadRequested.connect(self._on_load)

        return self.box

    def cmd(self, *args):
        """Run a single Siril command, logging it first."""
        self.context.siril.log(f"[CMD] {' '.join(args)}", LogColor.GREEN)
        self.context.siril.cmd(*args)

    def get_key_name(self):
        """Returns the internal registry key of the plugin."""
        return self.key_name

    def get_plugin_name(self):
        """Returns the display title of the plugin."""
        return self.title

    def _on_process(self):
        """
        Handler for the "Process" button: runs ``process()``, always returns
        to the original working directory afterwards, then runs ``load()``
        (if defined) so the result is immediately reflected in the UI.
        """
        workdir = self.get_siril_wd()
        has_load = type(self).load is not BatchPlugin.load
        try:
            self.process()
        except Exception as e:
            self.context.siril.log(f"Error during execution: {e}", LogColor.RED)
        self.cmd("cd", workdir)
        if has_load:
            self.load()

    def _on_load(self):
        """Handler for the "Load" button."""
        self.load()

    def process(self):
        """Override to implement the plugin's main batch action. No-op by default."""
        pass

    def load(self):
        """Override to implement a lightweight preview/load action. No-op by default."""
        pass

    def siril(self):
        """Convenience accessor for the shared Siril interface."""
        return self.context.siril

    def get_siril_wd(self):
        """Convenience accessor for Siril's current working directory."""
        return self.context.siril.get_siril_wd()

    def get_value(self, key: str):
        """Read the current value of one of this plugin's config widgets."""
        return self.box.get_value(key)

    @property
    def config(self):
        """The plugin's persisted settings dict (as loaded in ``set_up``)."""
        return self.context.config

    @config.setter
    def config(self, value):
        self.context.config = value


@dataclass
class BatchPluginEntry:
    """
    Static metadata describing one registered plugin type, as produced by
    ``@BatchPluginRegistry.register(...)``. This is the "blueprint"; call
    ``instantiate()`` to get a live ``BatchPlugin`` bound to a context.
    """

    plugin_cls: Type[BatchPlugin]
    key: str
    title: str
    items: "PluginItem"
    columns: int = 5
    enabled: bool = True

    def instantiate(self, siril: Any, config: dict) -> BatchPlugin:
        """Create and set up a fresh plugin instance from this entry."""
        instance = self.plugin_cls(siril,config)
        instance.set_up(
            key=self.key,
            title=self.title,
            items=self.items,
            columns=self.columns,
        )
        return instance


class BatchPluginRegistry:
    """
    Global registry of all available plugin types.

    Plugin modules register themselves with the ``@BatchPluginRegistry.register(...)``
    class decorator at import time (see ``load_plugins``), so simply importing a
    plugin module is enough to make it available in the UI.
    """

    _entries: list[BatchPluginEntry] = []

    # ------------------------------------------------------------------
    @classmethod
    def register(
        cls, key: str, title: str, items: "PluginItem", columns: int = 5, enabled: bool = True
    ):
        """Class decorator: wraps a ``BatchPlugin`` subclass and registers its metadata."""

        def decorator(plugin_cls: Type[BatchPlugin]):
            cls._entries.append(
                BatchPluginEntry(
                    plugin_cls=plugin_cls,
                    key=key,
                    title=title,
                    items=items,
                    columns=columns,
                    enabled=enabled,
                )
            )
            return plugin_cls

        return decorator

    @classmethod
    def all(cls) -> list[BatchPluginEntry]:
        """Return every registered plugin entry (enabled or not)."""
        return cls._entries

    # ------------------------------------------------------------------
    @classmethod
    def get(
        cls,
        key: str,
    ) -> Optional[BatchPluginEntry]:
        """Look up a registered entry by its key, or None if not found."""

        for entry in cls._entries:

            if entry.key == key:
                return entry

        return None

    # ------------------------------------------------------------------
    @classmethod
    def clear(cls):
        """Remove all registered entries (mainly useful for tests)."""
        cls._entries.clear()


@dataclass
class BatchPluginInstance:
    """
    A live plugin placed into the batch by the user, pairing its static
    ``entry`` with the running ``instance``, the ``widget`` (its config box),
    and the ``row`` container widget that holds both the box and its
    up/down/remove buttons inside ``PluginContainer``.
    """

    entry: BatchPluginEntry
    instance: BatchPlugin
    widget: PluginConfigBox
    row: Optional[QWidget] = None


class PluginContainer(QWidget):
    """
    Drop target and vertical list manager for the plugins the user has added
    to the current batch.

    Plugins are dragged in from ``PluginList`` (identified by their registry
    key via Qt's mime data) and rendered as a stack of rows, each pairing a
    plugin's ``PluginConfigBox`` with up/down/remove controls. Row widgets are
    created once per instance and reused across reordering; see the notes on
    ``_rebuild_layout`` for why.
    """

    def __init__(
        self,
        registry: BatchPluginRegistry,
        siril: Any,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)

        self.registry = registry
        self.siril = siril
        self.instances: list[BatchPluginInstance] = []

        self.setAcceptDrops(True)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(8, 8, 8, 8)
        self.layout.setSpacing(2)  # tight vertical gap between stacked plugin rows
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._empty_label: Optional[QLabel] = None

        self._show_empty_label()

    # ==================================================================
    # EMPTY STATE
    # ==================================================================

    def _show_empty_label(self):
        """Show the "Drag a plugin here" placeholder (no-op if already shown)."""

        if self._empty_label is not None:
            return

        self._empty_label = QLabel("Drag a plugin here")

        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._empty_label.setMinimumHeight(100)

        self.layout.addWidget(self._empty_label)

    # ------------------------------------------------------------------

    def _remove_empty_label(self):
        """Remove the "Drag a plugin here" placeholder, if currently shown."""

        if self._empty_label is None:
            return

        self.layout.removeWidget(self._empty_label)

        self._empty_label.deleteLater()

        self._empty_label = None

    # ==================================================================
    # DRAG & DROP
    # ==================================================================

    def dragEnterEvent(self, event):
        """Accept the drag only if it carries a plugin key known to the registry."""

        if not event.mimeData().hasText():
            event.ignore()
            return

        key = event.mimeData().text()

        entry = self.registry.get(key)

        if entry is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    # ------------------------------------------------------------------

    def dragMoveEvent(self, event):
        """Same acceptance check as dragEnterEvent, re-run as the drag moves over us."""

        if not event.mimeData().hasText():
            event.ignore()
            return

        key = event.mimeData().text()

        entry = self.registry.get(key)

        if entry is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    # ------------------------------------------------------------------
    def dropEvent(self, event):
        """Resolve the dropped plugin key against the registry and add it to the batch."""

        if not event.mimeData().hasText():
            event.ignore()
            return

        key = event.mimeData().text()

        entry = self.registry.get(key)

        if entry is None:
            event.ignore()
            return

        instance = self.add_plugin(entry)

        if instance is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    # ==================================================================
    # ADD PLUGIN
    # ==================================================================
    def add_plugin( self, entry: BatchPluginEntry, config: Optional[dict] = None ) -> Optional[BatchPluginInstance]:
        """
        Instantiate ``entry``, build its config box, wrap it in a row with
        move/remove buttons, and append it to the batch.

        Returns None (and logs the reason) if the plugin is already present
        or if instantiation fails, so callers can react without a partially
        set up instance being added.
        """

        # --------------------------------------------------------------
        # Prevent duplicate plugins
        # --------------------------------------------------------------

        for existing in self.instances:

            if existing.entry.key == entry.key:

                self.siril.log(
                    f"Plugin already added: {entry.title}",
                    LogColor.RED,
                )

                return None

        # --------------------------------------------------------------
        # Create plugin instance
        # --------------------------------------------------------------

        try:
            print("Init plugin")
            plugin = entry.plugin_cls(self.siril, config)

            print("setup plugin")
            plugin.set_up(
                key=entry.key,
                title=entry.title,
                items=entry.items,
                columns=entry.columns,
            )

            print("create box")
            widget = plugin.create_plugin_box()

            print("set config")

            # Restore saved configuration
            if config is not None:
                widget.set_config(config)

        except Exception as e:

            self.siril.log(
                f"Error creating plugin " f"{entry.title}: {e}",
                LogColor.RED,
            )

            return None

        # --------------------------------------------------------------
        # Create instance
        #
        # The row is created ONCE and stored in the instance.
        # This is important.
        # --------------------------------------------------------------

        instance = BatchPluginInstance(
            entry=entry,
            instance=plugin,
            widget=widget,
            row=None,
        )

        # --------------------------------------------------------------
        # Create row
        # --------------------------------------------------------------

        row = self._create_plugin_row(instance)

        instance.row = row

        # --------------------------------------------------------------
        # Store instance
        # --------------------------------------------------------------

        self.instances.append(instance)

        # --------------------------------------------------------------
        # Update layout
        # --------------------------------------------------------------

        self._remove_empty_label()

        self._rebuild_layout()

        self.siril.log(
            f"Added plugin: {entry.title}",
            LogColor.GREEN,
        )

        return instance

    # ==================================================================
    # RUN THE PLUGINS
    # ==================================================================
    def run_plugins(self):
        """Execute all configured plugins sequentially in their displayed order."""
        for instance in list(self.instances):
            self.siril.log(
                f"Running plugin: {instance.entry.title}",
                LogColor.GREEN,
            )

            try:
                # Uses the same process/load behavior as the plugin's Process button.
                instance.instance._on_process()
            except Exception as error:
                self.siril.log(
                    f"Error running plugin {instance.entry.title}: {error}",
                    LogColor.RED,
                )
    # ==================================================================
    # CREATE PLUGIN ROW
    # ==================================================================
    def _create_plugin_row(
        self,
        instance: BatchPluginInstance,
    ) -> QWidget:
        """Place the plugin group box on the left and controls on the right."""

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)

        # Group box on the left.
        row_layout.addWidget(
            instance.widget,
            1,
            Qt.AlignmentFlag.AlignTop,
        )

        # Controls on the right.
        button_layout = QVBoxLayout()
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(2)

        up_button = QPushButton("▲")
        down_button = QPushButton("▼")
        remove_button = QPushButton("✕")

        for button in (up_button, down_button, remove_button):
            button.setFixedSize(32, 28)

        up_button.setToolTip("Move plugin up")
        down_button.setToolTip("Move plugin down")
        remove_button.setToolTip("Remove plugin")

        button_layout.addWidget(up_button)
        button_layout.addWidget(down_button)
        button_layout.addWidget(remove_button)
        button_layout.addStretch()

        row_layout.addLayout(button_layout)

        up_button.clicked.connect(
            lambda checked=False, obj=instance: self._move_instance_up(obj)
        )
        down_button.clicked.connect(
            lambda checked=False, obj=instance: self._move_instance_down(obj)
        )
        remove_button.clicked.connect(
            lambda checked=False, obj=instance: self._remove_instance(obj)
        )

        return row

    # ==================================================================
    # MOVE PLUGIN UP
    # ==================================================================

    def _move_instance_up(
        self,
        instance: BatchPluginInstance,
    ):
        """Swap ``instance`` with its predecessor in the list, then redraw the stack."""

        if instance not in self.instances:
            return

        index = self.instances.index(instance)

        if index <= 0:
            return

        # Swap the instances
        self.instances[index - 1], self.instances[index] = (
            self.instances[index],
            self.instances[index - 1],
        )

        self._rebuild_layout()

    # ==================================================================
    # MOVE PLUGIN DOWN
    # ==================================================================

    def _move_instance_down(
        self,
        instance: BatchPluginInstance,
    ):
        """Swap ``instance`` with its successor in the list, then redraw the stack."""

        if instance not in self.instances:
            return

        index = self.instances.index(instance)

        if index >= len(self.instances) - 1:
            return

        # Swap the instances
        self.instances[index + 1], self.instances[index] = (
            self.instances[index],
            self.instances[index + 1],
        )

        self._rebuild_layout()

    # ==================================================================
    # REMOVE PLUGIN
    # ==================================================================

    def _remove_instance(
        self,
        instance: BatchPluginInstance,
    ):
        """Drop ``instance`` from the batch and delete its row widget."""

        if instance not in self.instances:
            return

        self.instances.remove(instance)

        # --------------------------------------------------------------
        # Delete the ROW, not the PluginConfigBox directly.
        #
        # The PluginConfigBox belongs to the row.
        # --------------------------------------------------------------

        if instance.row is not None:

            self.layout.removeWidget(instance.row)

            instance.row.deleteLater()

            instance.row = None

        # --------------------------------------------------------------
        # Show empty state when no plugins remain
        # --------------------------------------------------------------

        if not self.instances:

            self._show_empty_label()

    # ==================================================================
    # REBUILD LAYOUT
    # ==================================================================

    def _rebuild_layout(self):
        """Rebuild the plugin rows in compact top-to-bottom order."""

        while self.layout.count():
            self.layout.takeAt(0)

        for instance in self.instances:
            if instance.row is not None:
                instance.row.setSizePolicy(
                    QSizePolicy.Policy.Expanding,
                    QSizePolicy.Policy.Maximum,
                )
                self.layout.addWidget(instance.row)

        # Keep all rows grouped at the top; do not add a stretch item.
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)

    # ==================================================================
    # GET PLUGIN ORDER
    # ==================================================================

    def get_plugin_order(self) -> list[str]:
        """Return the registry keys of the current plugins, in their displayed order."""

        return [instance.entry.key for instance in self.instances]

    # ==================================================================
    # GET CONFIGURATION
    # ==================================================================

    def get_config(self) -> list[dict]:
        """Serialize the whole batch (order + each plugin's settings) for saving."""

        result = []

        for instance in self.instances:

            result.append(
                {
                    "key": instance.entry.key,
                    "config": instance.widget.get_config(),
                }
            )

        return result

    # ==================================================================
    # CLEAR ALL PLUGINS
    # ==================================================================

    def clear_plugins(self):
        """Remove every plugin from the batch and show the empty-state placeholder again."""

        # --------------------------------------------------------------
        # Remove and delete each row.
        #
        # Deleting the row also deletes the PluginConfigBox contained
        # inside that row.
        # --------------------------------------------------------------

        for instance in self.instances:

            if instance.row is not None:

                self.layout.removeWidget(instance.row)

                instance.row.deleteLater()

                instance.row = None

        # --------------------------------------------------------------
        # Clear instance list
        # --------------------------------------------------------------

        self.instances.clear()

        # --------------------------------------------------------------
        # Remove empty label if it exists
        # --------------------------------------------------------------

        if self._empty_label is not None:

            self.layout.removeWidget(self._empty_label)

            self._empty_label.deleteLater()

            self._empty_label = None

        # --------------------------------------------------------------
        # Show empty state
        # --------------------------------------------------------------

        self._show_empty_label()

    # ==================================================================
    # LOAD CONFIGURATION
    # ==================================================================

    def load_config(
        self,
        plugins_config: list[dict],
    ):
        """Replace the current batch with the plugins described by ``plugins_config``
        (the same shape produced by ``get_config``)."""

        # --------------------------------------------------------------
        # Remove current plugins
        # --------------------------------------------------------------

        self.clear_plugins()

        if not plugins_config:
            return

        # --------------------------------------------------------------
        # Restore plugins
        # --------------------------------------------------------------

        for plugin_data in plugins_config:

            if not isinstance(
                plugin_data,
                dict,
            ):
                continue

            key = plugin_data.get("key")

            if not key:
                continue

            entry = self.registry.get(key)

            if entry is None:

                self.siril.log(
                    f"Plugin not found: {key}",
                    LogColor.RED,
                )

                continue

            config = plugin_data.get(
                "config",
                {},
            )

            self.add_plugin(
                entry,
                config=config,
            )


class PluginList(QListWidget):
    """
    Sidebar list of available (enabled) plugins that the user can drag into
    the ``PluginContainer`` to add them to the batch.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self.setDragEnabled(True)
        self.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.setAlternatingRowColors(True)

    def populate(self, plugins: list[BatchPluginEntry]):
        """Refill the list from the registry, skipping disabled entries."""
        self.clear()
        for plugin in plugins:
            if not plugin.enabled:
                continue

            item = QListWidgetItem(plugin.title)
            item.setData(Qt.ItemDataRole.UserRole, plugin.key)
            item.setToolTip(plugin.key)
            self.addItem(item)

    def startDrag(self, supportedActions):
        """Begin a drag carrying the selected plugin's registry key as plain text."""

        item = self.currentItem()
        if item is None:
            return

        plugin_key = item.data(Qt.ItemDataRole.UserRole)

        if not plugin_key:
            return

        mime_data = QMimeData()
        mime_data.setText(str(plugin_key))

        drag = QDrag(self)
        drag.setMimeData(mime_data)

        # Small drag icon
        pixmap = QPixmap(160, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        drag.setPixmap(pixmap)
        drag.exec(Qt.DropAction.CopyAction)


class Batch(QMainWindow):
    """Main application window: connects to Siril, loads config, and builds the UI."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.siril = self.connect_to_siril()

        if self.siril is None:
            self.initialization_successful = False
            return
        
        self.siril.log(f"read config", LogColor.GREEN)
        self.config = BatchConfig(self.siril)
        self.presets = self.config.readPresetConfig()
        # Load the plugins
        self.siril.log(f"load plugins", LogColor.GREEN)
        
        self.createWindow()

        self.initialization_successful = True

    def connect_to_siril(self):
        """Establish the connection to the running Siril instance."""
        try:
            siril = s.SirilInterface()
            siril.connect()
            siril.log("Connected to Siril", LogColor.GREEN)
            return siril
        except Exception as error:
            print(f"Failed to connect to Siril: {error}")
            return None

    def createWindow(self):
        """Build the main layout: info panel, plugin sidebar, drop-target batch area, footer."""
        self.setWindowTitle(f"{APP_NAME} - v{VERSION}")
        self.resize(900, 600)

        central = QWidget()

        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        content_layout = QHBoxLayout()

        info_box = QGroupBox()
        info_layout = QVBoxLayout(info_box)
        info_label = QLabel("Information")
        info_layout.addWidget(info_label)

        workdir = self.siril.get_siril_wd()
        cwd_label = QLabel(f"Current Working Directory: {workdir}")
        cwd_label.setWordWrap(True)
        info_layout.addWidget(cwd_label)

        main_layout.addWidget(info_box)
        # --------------------------------------------------------------------
        # Plugin List
        # --------------------------------------------------------------------
        left_layout = QVBoxLayout()

        batch_label = QLabel("Batch")
        left_layout.addWidget(batch_label)
        self.batch_combo = QComboBox()
        self.batch_combo.setEditable(True)
        # We add new names ourselves (in _save_current_batch); don't let Qt
        # silently insert whatever the user is currently typing.
        self.batch_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._populate_batch_combo()
        left_layout.addWidget(self.batch_combo)

        left_label = QLabel("Available Plugins")
        left_layout.addWidget(left_label)
        self.plugin_list = PluginList()
        self.plugin_list.populate(BatchPluginRegistry.all())
        left_layout.addWidget(self.plugin_list)
        content_layout.addLayout(left_layout, 1)

        # --------------------------------------------------------------------
        # CENTER
        # --------------------------------------------------------------------
        center_layout = QVBoxLayout()
        center_label = QLabel("Batch Processing")

        center_layout.addWidget(center_label)
        # Scroll area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAcceptDrops(True)
        # Plugin container
        self.plugin_container = PluginContainer(registry=BatchPluginRegistry, siril=self.siril)

        self.scroll_area.setWidget(self.plugin_container)
        center_layout.addWidget(self.scroll_area)
        content_layout.addLayout(center_layout, 3)

        main_layout.addLayout(content_layout, 1)

        # The combo needs self.plugin_container to exist before it can load a
        # batch, so it's only wired up (and the initial selection applied)
        # here, after both sides of the window have been built.
        #
        # textActivated (not currentTextChanged) fires only when the user
        # explicitly picks an entry from the dropdown - not on every
        # keystroke while typing a new batch name - so typing a new name
        # never wipes out the plugin list being built for it.
        self.batch_combo.textActivated.connect(self._on_batch_selected)
        self._load_batch(self.batch_combo.currentText())

        # --------------------------------------------------------------------
        # Footer
        # --------------------------------------------------------------------

        main_layout.addLayout(self._create_buttons_layout())

    # ------------------------------------------------------------------
    # BATCH PRESETS (from Batches: section of origin_m2_presets.yaml)
    # ------------------------------------------------------------------
    def _populate_batch_combo(self):
        """
        Fill the batch selector with every name found under the presets
        file's ``Batches:`` section, plus a synthetic "empty" entry
        (selected by default) for "start with no plugins".
        """
        batches = self.presets.get("Batches", {}) if isinstance(self.presets, dict) else {}
        names = [name for name in batches.keys() if name != "empty"]

        self.batch_combo.addItem("empty")
        self.batch_combo.addItems(names)
        self.batch_combo.setCurrentText("empty")

    def _on_batch_selected(self, name: str):
        """Slot for the batch combo box: (re)build the plugin list for the chosen batch."""
        self._load_batch(name)

    def _load_batch(self, name: str):
        """
        Replace the current batch contents with the plugins defined for
        preset batch ``name``, restoring each plugin's saved config values.

        A batch whose value isn't a list (e.g. the "empty" batch, or any
        placeholder value in the YAML) is treated as an empty batch.
        """
        self.plugin_container.clear_plugins()

        batches = self.presets.get("Batches", {}) if isinstance(self.presets, dict) else {}
        entries = batches.get(name)

        if not isinstance(entries, list):
            return

        for item in entries:
            if not isinstance(item, dict):
                continue

            plugin_key = item.get("plugin")
            if not plugin_key:
                continue

            entry = BatchPluginRegistry.get(plugin_key)
            if entry is None:
                self.siril.log(
                    f"Batch '{name}': unknown plugin '{plugin_key}'",
                    LogColor.RED,
                )
                continue

            # The YAML uses "config: none" for plugins that take no settings;
            # only pass a dict through to add_plugin/set_config.
            config = item.get("config")
            if not isinstance(config, dict):
                config = None

            self.plugin_container.add_plugin(entry, config=config)

    def _save_current_batch(self):
        """
        Save the current plugin list under the name shown in the batch combo.

        If that name is new, it's added to the presets file (and to the
        combo's list); if it already exists, its stored plugin list and
        configs are overwritten with the current ones. Either way the
        presets file is persisted to disk immediately.
        """
        name = self.batch_combo.currentText().strip()

        if not name:
            self.siril.log("Cannot save a batch with an empty name", LogColor.RED)
            return

        if name == "empty":
            self.siril.log(
                '"empty" is reserved for an empty batch and cannot be overwritten',
                LogColor.RED,
            )
            return

        entries = [
            {"plugin": item["key"], "config": item["config"]}
            for item in self.plugin_container.get_config()
        ]

        if not isinstance(self.presets, dict):
            self.presets = {}
        batches = self.presets.setdefault("Batches", {})
        is_new = name not in batches
        batches[name] = entries

        self.config.storePresets(self.presets)

        if is_new:
            self.batch_combo.addItem(name)

        # Reflect the (possibly new) name in the combo without re-triggering
        # a reload - the container already holds exactly what was just saved.
        self.batch_combo.blockSignals(True)
        self.batch_combo.setCurrentText(name)
        self.batch_combo.blockSignals(False)

        self.siril.log(
            f"Batch '{name}' {'created' if is_new else 'updated'} and saved",
            LogColor.GREEN,
        )

    def _run_batch(self):
        """Run every plugin instance sequentially."""
        self.run_button.setEnabled(False)
        try:
            self.plugin_container.run_plugins()
        finally:
            self.run_button.setEnabled(True)

    def _create_buttons_layout(self):
        """Build the footer button row (Save Presets, Close, Run)."""
        footer = QHBoxLayout()
        footer.setContentsMargins(12, 10, 12, 12)
        footer.setSpacing(8)

        #        help_button = QPushButton("Help")
        #        help_button.setMinimumWidth(50)
        #        help_button.setMinimumHeight(35)
        #        help_button.setToolTip("Show help information and frequently asked questions")
        #        help_button.clicked.connect(self.show_help)
        #        button_layout.addWidget(help_button)

        save_presets_button = QPushButton("Save Presets")
        save_presets_button.setMinimumWidth(80)
        save_presets_button.setMinimumHeight(35)
        save_presets_button.setToolTip(
            "Save the current plugin list as the batch shown in the Batch selector "
            "(creates it if the name is new, otherwise updates it)."
        )
        save_presets_button.clicked.connect(self._save_current_batch)
        footer.addWidget(save_presets_button)


        #       button_layout.addStretch()
        close_button = QPushButton("Close")
        close_button.setMinimumWidth(80)
        close_button.setMinimumHeight(35)
        close_button.clicked.connect(self.close_dialog)
        footer.addWidget(close_button)

        footer.addSpacing(10)

        self.run_button = QPushButton("Run")
        self.run_button.setMinimumWidth(100)
        self.run_button.setMinimumHeight(35)
        self.run_button.setStyleSheet(
            "QPushButton { background-color: #0078cc; color: white; font-weight: bold; border-radius: 4px; } QPushButton:hover { background-color: #33abff; }"
        )
        self.run_button.clicked.connect(self._run_batch)
        footer.addWidget(self.run_button)

        return footer

    def close_dialog(self):
        """Disconnect from Siril and close the window."""
        if self.siril is not None:
            self.siril.disconnect()
        self.close()


def load_plugins(plugin_dir: str) -> None:
    """
    Import every ``.py`` module in the plugins package (skipping files
    starting with "_", e.g. ``__init__.py``).

    Importing is enough to register a plugin: each module's
    ``@BatchPluginRegistry.register(...)``-decorated class runs its
    decorator as a side effect of the import, populating
    ``BatchPluginRegistry._entries``.
    """
    plugin_path = pathlib.Path(plugin_dir)
    print(f"{plugin_path.absolute()}")
    for file in plugin_path.glob("*.py"):
        if file.stem.startswith("_"):
            continue  # e.g. skip __init__.py
        print(f"load {file.name}")
        spec = importlib.util.spec_from_file_location(file.stem, file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)


def sirilBatch(argv):
    """Application entry point: load plugins, build the Qt app, and run the main window."""
    try:
        plugin = os.path.dirname(os.path.realpath(__file__)) + "/plugins"
        load_plugins(plugin)

        app = QApplication(argv)
        batch = Batch()

        # Only show window if initialization was successful
        if batch.initialization_successful:
            batch.show()
            sys.exit(app.exec())
        else:
            # User canceled during initialization - exit gracefully
            sys.exit(0)
    except Exception as e:
        print(f"Error initializing application: {str(e)}")
        sys.exit(1)