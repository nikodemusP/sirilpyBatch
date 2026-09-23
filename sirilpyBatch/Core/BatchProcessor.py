# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Nikolas Pommerening
# Contact: nikodemus.p@gmx.at
#
from dataclasses import dataclass
from typing import Any, Optional

import sirilpy as s # type: ignore
from sirilpy import LogColor # type: ignore

from PyQt6.QtCore import QMimeData, Qt
from PyQt6.QtGui import QPixmap, QDrag
from PyQt6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QSizePolicy,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QGroupBox,
    QScrollArea,
)

from sirilpyBatch import APP_NAME, VERSION

from .PluginItem import PluginItem
from .BatchConfig import BatchConfig
from .Registry import BatchPluginRegistry
from .PluginEntry import BatchPluginEntry  # re-exported for backwards compatibility
from .PluginConfigBox import PluginConfigBox
from .BatchPlugin import BatchPlugin



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
        config: BatchConfig,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)

        self.registry = registry
        self.siril = siril
        self.config = config
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
    def add_plugin( self, entry: BatchPluginEntry, plugin_config: Optional[dict] = None ) -> Optional[BatchPluginInstance]:
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
            plugin = entry.instantiate(self.siril, self.config)

            widget = plugin.create_plugin_box()

            # Restore saved configuration
            if plugin_config is not None:
                widget.set_config(plugin_config)

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
    # Refresh Plugins
    # ==================================================================
    def refresh_plugin_widgets(self):
        """Baut die Benutzeroberflächen aller aktiven Plugins neu auf, um geänderte Config-Werte zu laden."""
        for instance in self.instances:
            # 1. Aktuelle Benutzereingaben sichern
            current_config = instance.widget.get_config()
            
            # 2. Altes Widget aus dem Zeilen-Layout entfernen und löschen
            row_layout = instance.row.layout()
            row_layout.removeWidget(instance.widget)
            instance.widget.deleteLater()
            
            # 3. Neues Widget mit aktualisiertem Context generieren
            instance.widget = instance.instance.create_plugin_box()
            
            # 4. Vorherige Werte wiederherstellen (sofern sie noch in den neuen Listen existieren)
            instance.widget.set_config(current_config)
            
            # 5. Widget wieder ganz links in die Zeile einfügen
            row_layout.insertWidget(0, instance.widget, 1, Qt.AlignmentFlag.AlignTop)

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
        self.resize(900, 800)

        central = QWidget()

        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        content_layout = QHBoxLayout()

        # --------------------------------------------------------------------
        # Info Box
        # --------------------------------------------------------------------
        info_box = QGroupBox()
        info_layout = QVBoxLayout(info_box)
        info_label = QLabel("Information")
        info_layout.addWidget(info_label)

        workdir = self.siril.get_siril_wd()
        cwd_label = QLabel(f"Current Working Directory: {workdir}")
        cwd_label.setWordWrap(True)
        info_layout.addWidget(cwd_label)

        self.telescope_combo = QComboBox(info_box)

        telescopes = self.config.telescope_list()
        self.telescope_combo.addItems(
            [telescope["name"] for telescope in telescopes]
        )

        selected = self.config.selected_telescope_name()
        index = self.telescope_combo.findText(selected)
        if index >= 0:
            self.telescope_combo.setCurrentIndex(index)

        def on_telescope_changed(name):
            self.config.set_selected_telescope(name)
            self.plugin_container.refresh_plugin_widgets()

        self.telescope_combo.currentTextChanged.connect(on_telescope_changed)

        info_layout.addWidget(QLabel("Telescope:"))
        info_layout.addWidget(self.telescope_combo)

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
        self.plugin_container = PluginContainer(registry=BatchPluginRegistry, siril=self.siril, config=self.config)

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
        batches = self.config.get_value("Batches", {})
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

        batches = self.config.get_value("Batches", {})
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
            plugin_config = item.get("config")
            if not isinstance(plugin_config, dict):
                plugin_config = None

            self.plugin_container.add_plugin(entry, plugin_config=plugin_config)

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

        batches = self.config.get_value("Batches", {})
        is_new = name not in batches
        batches[name] = entries

        self.config.storePresets({"Batches": batches})

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