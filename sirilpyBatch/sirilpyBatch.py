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

from copy import deepcopy
from dataclasses import dataclass, field, fields
import importlib.util
import json
import os
import pathlib
import sys
import textwrap
from pathlib import Path
from typing import Any, Optional, Type, Union

import yaml
import sirilpy as s
from sirilpy import LogColor

from PyQt6.QtCore import QMimeData, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QDrag, QPainter
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
      * ``sirilpyBatch.yaml``    - user-wide presets, stored in Siril's user data
                                   directory so they survive across projects.
    """

    def __init__(self, siril):
        self.siril = siril
        config_dir = Path(siril.get_siril_userdatadir())
        config_dir.mkdir(parents=True, exist_ok=True)
        self.presets_file = Path(__file__).resolve().with_name("sirilpyBatch.yaml")
        self.global_config_file = Path(__file__).resolve().with_name("sirilpyConfig.yaml")
        self._readConfig()

    def get_value(self, key: str, default: Any = None):
        """Resolve values such as telescope.focalLen."""
        parts = key.split(".")
        value = self.config
        for part in parts:
            print(f"{part}\n")
            value = value.get(part)
            print(f"{value}\n")
            if value == None:
                return default
        return value        

    def _readConfig(self):
        global_config = self._readGlobalConfig() or {}
        preset_config = self._readPresetConfig() or {}
        self.config   = {
            **global_config,
            **preset_config,            
        }

    def _readGlobalConfig(self):
        """Load the shared telescope/sensor configuration."""
        if not self.global_config_file.exists():
            self.siril.log(
                f"Global config not found: {self.global_config_file}",
                LogColor.RED,
            )
            return {}

        try:
            with open(self.global_config_file, "r", encoding="utf-8") as file:
                config = yaml.safe_load(file)

            self.siril.log(
                "Global configuration loaded successfully.",
                LogColor.GREEN,
            )
            return config if isinstance(config, dict) else {}

        except Exception as error:
            self.siril.log(
                f"Error reading global config: {error}",
                LogColor.RED,
            )
            return {}

    def _readPresetConfig(self):
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
            config["telescope"] = self.config.get("telescope", {})
            with open(self.presets_file, "w") as f:
                yaml.safe_dump(config, f)
                self._readConfig()
                self.siril.log("Configuration saved successfully.", LogColor.GREEN)
        except Exception as e:
            self.siril.log(f"Error saving configuration file: {str(e)}", LogColor.RED)

    def telescope_list(self):
        return self.config.get("telescopes", [])

    def selected_telescope_name(self):
        return self.config.get("telescope", {}).get("name", "")

    def set_selected_telescope(self, name):
        selected_telescope = next(
            (
                telescope
                for telescope in self.telescope_list()
                if telescope.get("name") == name
            ),
            None,
        )

        if selected_telescope is not None:
            self.config["telescope"] = deepcopy(selected_telescope)


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
    config: BatchConfig
    plugin_config: dict

def resolve_config_value(value: Any, context: Optional[BatchContext]) -> Any:
    """Löst Werte auf, die mit @ beginnen, unter Verwendung von BatchConfig."""
    if isinstance(value, str) and value.startswith("@"):
        if context and context.config:
            # Entfernt das '@' und holt den Pfad (z.B. "telescope.filter")
            return context.config.get_value(value[1:])
    return value

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

    def create_widget(self, context: Optional[BatchContext] = None) -> QWidget:
        raise NotImplementedError

    def bind_widget(self, widget: QWidget, callback):
        raise NotImplementedError

    def get_value(self, widget: QWidget) -> Any:
        raise NotImplementedError

    def set_value(self, widget: QWidget, value: Any):
        raise NotImplementedError
    
@dataclass
class SeparatorItem(PluginItem):
    def create_widget(self):
        return None

    def bind_widget(self, widget, callback):
        pass

    def get_value(self, widget):
        return None

    def set_value(self, widget, value):
        pass


@dataclass
class CheckboxItem(PluginItem):
    labelPos: str = "RIGHT"

    def create_widget(self, context: Optional[BatchContext] = None) -> QWidget:
        widget = QCheckBox()
        resolved_default = resolve_config_value(self.default, context)
        widget.setChecked(bool(resolved_default if resolved_default is not None else False))
        return widget

    def bind_widget(self, widget, callback):
        widget.stateChanged.connect(
            lambda state, key=self.key: callback(
                state == Qt.CheckState.Checked.value,
                key,
            )
        )

    def get_value(self, widget):
        return widget.isChecked()

    def set_value(self, widget, value):
        widget.setChecked(bool(value))

@dataclass
class NumberItem(PluginItem):
    step: float = 1
    minimum: float = 0
    maximum: float = 100

    def bind_widget(self, widget, callback):
        widget.valueChanged.connect(
            lambda value, key=self.key: callback(value, key)
        )

    def get_value(self, widget):
        return widget.value()

    def set_value(self, widget, value):
        widget.setValue(value)

@dataclass
class SliderItem(NumberItem):
    def create_widget(self, context: Optional[BatchContext] = None) -> QWidget:
        widget = QSlider(Qt.Orientation.Horizontal)
        min_val = int(resolve_config_value(self.minimum, context))
        max_val = int(resolve_config_value(self.maximum, context))
        def_val = int(resolve_config_value(self.default, context) if self.default is not None else min_val)
        
        widget.setMinimum(min_val)
        widget.setMaximum(max_val)
        widget.setSingleStep(int(self.step))
        widget.setValue(def_val)
        return widget
    def set_value(self, widget, value):
        widget.setValue(int(value))

@dataclass
class IntItem(NumberItem):
    def create_widget(self, context: Optional[BatchContext] = None):
        widget = QSpinBox()
        min_val = int(resolve_config_value(self.minimum, context))
        max_val = int(resolve_config_value(self.maximum, context))
        def_val = int(resolve_config_value(self.default, context) if self.default is not None else min_val)

        widget.setMinimum(min_val)
        widget.setMaximum(max_val)
        widget.setSingleStep(int(self.step))
        widget.setValue(def_val)
        return widget
    def set_value(self, widget, value):
        widget.setValue(int(value))
    
@dataclass
class FloatItem(NumberItem):
    decimals: int = 2

    def create_widget(self, context: Optional[BatchContext] = None):
        widget = QDoubleSpinBox()
        min_val = float(resolve_config_value(self.minimum, context))
        max_val = float(resolve_config_value(self.maximum, context))
        def_val = float(resolve_config_value(self.default, context) if self.default is not None else min_val)

        widget.setMinimum(min_val)
        widget.setMaximum(max_val)
        widget.setSingleStep(float(self.step))
        widget.setDecimals(int(self.decimals))
        widget.setValue(def_val)
        return widget

@dataclass
class TextItem(PluginItem):
    def create_widget(self, context: Optional[BatchContext] = None):
        widget = QLineEdit()
        resolved_default = resolve_config_value(self.default, context)
        if resolved_default is not None:
            widget.setText(str(resolved_default))
        return widget

    def bind_widget(self, widget, callback):
        widget.textChanged.connect(
            lambda value, key=self.key: callback(value, key)
        )

    def get_value(self, widget):
        return widget.text()

    def set_value(self, widget, value):
        widget.setText(str(value))

@dataclass
class ComboBoxItem(PluginItem):
    values: list[Any] = field(default_factory=list)

    def create_widget(self, context: Optional[BatchContext] = None):
        widget = QComboBox()
        widget.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        widget.setMinimumContentsLength(6)
        
        resolved_values = resolve_config_value(self.values, context)
        if not isinstance(resolved_values, list):
            resolved_values = []
            
        for value in resolved_values:
            widget.addItem(str(value), userData=value)
            
        resolved_default = resolve_config_value(self.default, context)
        if resolved_default in resolved_values:
            widget.setCurrentIndex(resolved_values.index(resolved_default))
        return widget

    def bind_widget(self, widget, callback):
        widget.currentIndexChanged.connect(
            lambda _index, key=self.key, combo=widget: callback(combo.currentData(), key)
        )

    def get_value(self, widget):
        return widget.currentData()

    def set_value(self, widget, value):
        index = widget.findData(value)
        if index >= 0:
            widget.setCurrentIndex(index)

@dataclass
class RangeItem(PluginItem):
    minimum: int = 0
    maximum: int = 100

    def __post_init__(self):
        # YAML gives us "0,2" (a string) or [0, 2] (a list); normalise to a tuple.
        if isinstance(self.default, str):
            self.default = [part.strip() for part in self.default.split(",")]
        if self.default is not None:
            try:
                low, high = self.default
                self.default = (int(low), int(high))
            except (TypeError, ValueError):
                raise ValueError(
                    f"RangeItem '{self.key}': default must be two integers "
                    f"like '0,2' or [0, 2], got {self.default!r}"
                )

    def create_widget(self, context: Optional[BatchContext] = None):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        min_val = int(resolve_config_value(self.minimum, context))
        max_val = int(resolve_config_value(self.maximum, context))
        
        resolved_default = resolve_config_value(self.default, context)
        if isinstance(resolved_default, str):
            resolved_default = [int(part.strip()) for part in resolved_default.split(",")]

        low, high = resolved_default or (min_val, max_val)

        widget.low = QSpinBox()
        widget.high = QSpinBox()

        for spinbox, value in ((widget.low, low), (widget.high, high)):
            spinbox.setMinimum(min_val)
            spinbox.setMaximum(max_val)
            spinbox.setValue(int(value))
            layout.addWidget(spinbox)

        return widget

    def bind_widget(self, widget, callback):
        widget.low.valueChanged.connect(
            lambda _value: callback(self.get_value(widget), self.key)
        )
        widget.high.valueChanged.connect(
            lambda _value: callback(self.get_value(widget), self.key)
        )

    def get_value(self, widget):
        return widget.low.value(), widget.high.value()

    def set_value(self, widget, value):
        low, high = value
        widget.low.setValue(int(low))
        widget.high.setValue(int(high))
          
# ------------------------------------------------------------------------------------------
# YAML plugin definitions
#
# A plugin describes itself (registry entry, box layout and config widgets) as one YAML
# document, which is passed straight to ``@BatchPluginRegistry.register(...)``:
#
#     Plugin:
#         Key: color_calibration          # required, unique registry key
#         Title: Color Calibration        # optional, defaults to Key
#         Enabled: true                   # optional, false hides it from the sidebar
#     Box:
#         Columns: 6                      # optional, grid columns of the config box (default 5)
#     Items:
#         - CheckBox:
#             Key: pcc
#             Label: Photometric Color Calibration
#             Colspan: 2
#             Default: False
#         - Separator
#         - ComboBox:
#             Key: catalogue
#             Label: Catalogue
#             Values: [none, apass, gaia]
#             Default: gaia
#
# Section, item type and option names are case-insensitive. Item options map 1:1 onto the
# fields of the matching PluginItem dataclass (Key, Label, LabelPos, Default, Tooltip,
# Colspan, plus Values / Min / Max / Step / Decimals depending on the type).
# ------------------------------------------------------------------------------------------
def _norm(name: Any) -> str:
    """Case-insensitive comparison form; ignores ``_``, ``-`` and spaces."""
    return str(name).strip().lower().replace("_", "").replace("-", "").replace(" ", "")


ITEM_TYPES: dict[str, Type[PluginItem]] = {
    "checkbox": CheckboxItem,
    "separator": SeparatorItem,
    "seperator": SeparatorItem,  # common misspelling
    "combobox": ComboBoxItem,
    "combo": ComboBoxItem,
    "text": TextItem,
    "int": IntItem,
    "integer": IntItem,
    "float": FloatItem,
    "slider": SliderItem,
    "range": RangeItem,
    "intrange": RangeItem,
}

# Short spellings accepted in YAML -> real dataclass field name.
_OPTION_ALIASES = {"min": "minimum", "max": "maximum", "labelposition": "labelpos"}

def _build_item(type_name: Any, options: Any, where: str) -> PluginItem:
    """Create one PluginItem from its YAML type name and options mapping."""
    normalized = _norm(type_name)
    if normalized.endswith("item"):  # allow "CheckboxItem" as well as "Checkbox"
        normalized = normalized[: -len("item")]
    item_cls = ITEM_TYPES.get(normalized)
    if item_cls is None:
        raise ValueError(
            f"{where}: unknown item type '{type_name}' "
            f"(available: {', '.join(sorted(ITEM_TYPES))})"
        )

    if options is None:
        options = {}
    if not isinstance(options, dict):
        raise ValueError(f"{where}: options of '{type_name}' must be a mapping, got {options!r}")

    field_names = {f.name for f in fields(item_cls)}
    valid = {_norm(name): name for name in field_names}
    for alias, target in _OPTION_ALIASES.items():
        if target in field_names:
            valid[alias] = target

    kwargs: dict[str, Any] = {}
    for raw_key, value in options.items():
        name = valid.get(_norm(raw_key))
        if name is None:
            raise ValueError(
                f"{where}: unknown option '{raw_key}' for '{type_name}' "
                f"(valid: {', '.join(sorted(field_names))})"
            )
        kwargs[name] = value

    try:
        return item_cls(**kwargs)
    except ValueError as error:
        raise ValueError(f"{where}: {error}") from error


def _load_yaml(spec: Any, source: str) -> Any:
    """Parse ``spec`` if it is YAML text (dedented first); pass anything else through."""
    if not isinstance(spec, str):
        return spec
    try:
        return yaml.safe_load(textwrap.dedent(spec))
    except yaml.YAMLError as error:
        raise ValueError(f"{source}: invalid YAML: {error}") from error


def parse_plugin_items(
    spec: Union[str, dict, list, None], source: str = "plugin"
) -> list[PluginItem]:
    """
    Turn a plugin's item description into a list of ``PluginItem`` objects.

    ``spec`` may be YAML text (with a top-level ``Items:`` list), an already parsed
    dict/list, or - for backwards compatibility - a list of ready-made ``PluginItem``
    objects (which is passed through unchanged). Raises ``ValueError`` with a message
    naming ``source`` and the offending item if anything is malformed.
    """
    spec = _load_yaml(spec, source)

    if isinstance(spec, dict):
        matches = [value for key, value in spec.items() if _norm(key) == "items"]
        if not matches:
            raise ValueError(f"{source}: YAML must contain a top-level 'Items:' list")
        spec = matches[0]

    if spec is None:
        return []
    if not isinstance(spec, list):
        raise ValueError(f"{source}: 'Items' must be a list, got {type(spec).__name__}")

    items: list[PluginItem] = []
    seen_keys: set[str] = set()

    for index, element in enumerate(spec, start=1):
        where = f"{source}, item #{index}"

        if isinstance(element, PluginItem):
            item = element
        elif isinstance(element, str):  # bare "- Separator"
            item = _build_item(element, None, where)
        elif isinstance(element, dict) and len(element) == 1:  # "- CheckBox: {...}"
            ((type_name, options),) = element.items()
            item = _build_item(type_name, options, where)
        else:
            raise ValueError(
                f"{where}: expected 'TypeName' or a single 'TypeName: {{options}}' mapping, "
                f"got {element!r}"
            )

        if not isinstance(item, SeparatorItem):
            if item.key is None or str(item.key).strip() == "":
                raise ValueError(f"{where}: {type(item).__name__} needs a 'Key'")
            item.key = str(item.key)
            if item.key in seen_keys:
                raise ValueError(f"{where}: duplicate key '{item.key}'")
            seen_keys.add(item.key)
            if item.label is None:
                item.label = item.key

        items.append(item)

    return items


@dataclass
class PluginSpec:
    """Everything a plugin's YAML document describes."""

    key: str
    title: str
    items: list[PluginItem]
    columns: int = 5
    enabled: bool = True


_PLUGIN_SECTION_OPTIONS = {"key": "key", "title": "title", "enabled": "enabled"}
_BOX_SECTION_OPTIONS = {"columns": "columns"}


def _read_section(value: Any, section: str, allowed: dict[str, str], source: str) -> dict[str, Any]:
    """Return ``{option: value}`` for a ``Plugin:`` / ``Box:`` section, rejecting unknown options."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{source}: '{section}' must be a mapping of options")

    result: dict[str, Any] = {}
    for raw_key, option_value in value.items():
        name = allowed.get(_norm(raw_key))
        if name is None:
            raise ValueError(
                f"{source}: unknown option '{raw_key}' in '{section}' "
                f"(valid: {', '.join(sorted(allowed.values()))})"
            )
        result[name] = option_value
    return result


def parse_plugin_spec(spec: Union[str, dict], source: str = "plugin") -> PluginSpec:
    """
    Parse a plugin's YAML document (``Plugin:`` / ``Box:`` / ``Items:`` sections) into a
    ``PluginSpec``. Only ``Plugin: Key`` is mandatory. Raises ``ValueError`` with a message
    naming the plugin and the offending section/item if anything is malformed.
    """
    data = _load_yaml(spec, source)
    if not isinstance(data, dict):
        raise ValueError(
            f"{source}: expected a YAML mapping with 'Plugin:', 'Box:' and 'Items:' sections"
        )

    sections: dict[str, Any] = {}
    for name, value in data.items():
        normalized = _norm(name)
        if normalized not in ("plugin", "box", "items"):
            raise ValueError(
                f"{source}: unknown section '{name}' (valid: Plugin, Box, Items)"
            )
        sections[normalized] = value

    plugin = _read_section(sections.get("plugin"), "Plugin", _PLUGIN_SECTION_OPTIONS, source)
    key = plugin.get("key")
    if key is None or str(key).strip() == "":
        raise ValueError(f"{source}: the 'Plugin' section needs a 'Key'")
    key = str(key).strip()
    source = f"plugin '{key}'"  # from here on, errors name the plugin

    title = plugin.get("title")
    title = key if title is None else str(title)

    enabled = plugin.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError(f"{source}: 'Enabled' must be true or false, got {enabled!r}")

    box = _read_section(sections.get("box"), "Box", _BOX_SECTION_OPTIONS, source)
    columns = box.get("columns", 5)
    if isinstance(columns, bool) or not isinstance(columns, int) or columns < 1:
        raise ValueError(f"{source}: 'Columns' must be a positive integer, got {columns!r}")

    items = parse_plugin_items(sections.get("items"), source)

    return PluginSpec(key=key, title=title, items=items, columns=columns, enabled=enabled)


# ------------------------------------------------------------------------------------------
class ElidedLabel(QLabel):
    """
    Single-line label that prefers to show its full text but, when its column is too
    narrow, shrinks and elides the end with an ellipsis instead of forcing the whole
    plugin box wider. When elided, the full text is available as a tooltip.
    """

    _MIN_CHARS = 8  # roughly how much of the text stays readable at the smallest size

    def __init__(self, text: str = "", parent: Optional[QWidget] = None, auto_tooltip: bool = True):
        super().__init__(text, parent)
        self._auto_tooltip = auto_tooltip
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

    def minimumSizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        text = self.text()
        full = metrics.horizontalAdvance(text)
        shortest = full
        if len(text) > self._MIN_CHARS:
            shortest = metrics.horizontalAdvance(text[: self._MIN_CHARS] + "\u2026")
        hint = super().sizeHint()
        return QSize(hint.width() - full + min(full, shortest), hint.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._auto_tooltip:
            elided = self.fontMetrics().horizontalAdvance(self.text()) > self.contentsRect().width()
            self.setToolTip(self.text() if elided else "")

    def paintEvent(self, event):
        painter = QPainter(self)
        rect = self.contentsRect()
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, rect.width())
        self.style().drawItemText(
            painter,
            rect,
            int(self.alignment()),
            self.palette(),
            self.isEnabled(),
            text,
            self.foregroundRole(),
        )


# ------------------------------------------------------------------------------------------
class PluginConfigBox(QGroupBox):
    """
    A checkable group box that renders a plugin's ``PluginItem`` list as a
    grid of labeled widgets, plus an optional "Load" and/or "Process" button.
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
        context: Optional[BatchContext] = None,
    ):
        super().__init__(title, parent)

        self.items = list(items or [])
        self.columns = max(1, columns)
        self.context = context
        self.widgets: dict[str, QWidget] = {}
        self.item_by_key: dict[str, PluginItem] = {
            item.key: item
            for item in self.items
            if not isinstance(item, SeparatorItem) and item.key is not None
        }

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._create_ui(has_load=has_load, has_process=has_process)

    def _create_ui(self, has_load: bool, has_process: bool):
        main_layout = QVBoxLayout(self)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)

        row = 0
        column = 0
        used_columns = 0  # rightmost grid column any item actually occupies

        for item in self.items:
            if isinstance(item, SeparatorItem):
                if column != 0:
                    row += 1
                    column = 0
                line = QLabel()
                line.setFixedHeight(1)
                grid.addWidget(line, row, 0, 1, self.columns)
                row += 1
                continue

            widget = item.create_widget(self.context)
            if widget is None:
                continue

            span = max(1, min(item.colspan, self.columns))
            if column + span > self.columns:
                column = 0
                row += 1

            label = ElidedLabel(item.label or "", auto_tooltip=not item.tooltip)
            if item.tooltip:
                label.setToolTip(item.tooltip)
                widget.setToolTip(item.tooltip)

            cell = QHBoxLayout()
            cell.setContentsMargins(0, 0, 0, 0)
            cell.setSpacing(6)

            if isinstance(widget, QCheckBox):
                widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            else:
                widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

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
            used_columns = max(used_columns, column + span)
            self.widgets[item.key] = widget

            item.bind_widget(widget, lambda value, key: self.valueChanged.emit(key, value))

            column += span
            if column >= self.columns:
                column = 0
                row += 1

        # Only columns that hold something share the width. Columns no item ever reaches
        # (e.g. columns=6 but nothing beyond column 4) get no stretch, so they don't
        # steal space from the labels and widgets that do exist.
        for col in range(self.columns):
            grid.setColumnStretch(col, 1 if col < used_columns else 0)

        main_layout.addLayout(grid)

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

    def get_value(self, key: str) -> Any:
        widget = self.widgets.get(key)
        item = self.item_by_key.get(key)

        if widget is None or item is None:
            return None

        return item.get_value(widget)

    def set_config(self, config: Optional[dict[str, Any]]):
        if not config:
            return

        for item in self.items:
            if isinstance(item, SeparatorItem):
                continue
            if item.key not in config:
                continue
            widget = self.widgets.get(item.key)
            if widget is None:
                continue
            item.set_value(widget, config[item.key])

    def get_config(self) -> dict[str, Any]:
        cfg: dict[str, Any] = {}
        for item in self.items:
            if isinstance(item, SeparatorItem):
                continue
            cfg[item.key] = self.get_value(item.key)
        return cfg
    
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

    def __init__(self, siril: Any, config: BatchConfig ):
        self.context = BatchContext(
            siril=siril,
            config=config,
            plugin_config={},
        )

    def set_up(self, key: str, title: str, items: list[PluginItem], columns: int = 5, plugin_config: dict = {}):
        """Called once after construction to bind this instance to its registry entry."""
        self.plugin_items = items
        self.key_name = key
        self.title = title
        self.columns = columns
        self.context.plugin_config = plugin_config
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
            context=self.context
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

    def get_config(self, key: str, default):
        return self.context.config.get_value(key,default)
    
    def get_value(self, key: str):
        """Read the current value of one of this plugin's config widgets."""
        return self.box.get_value(key)

    @property
    def config(self):
        """The plugin's persisted settings dict (as loaded in ``set_up``)."""
        return self.context.plugin_config

    @config.setter
    def config(self, value):
        self.plugin_config.config = value


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
    items: list[PluginItem]
    columns: int = 5
    enabled: bool = True

    def instantiate(self, siril: Any, config: BatchConfig, plugin_config: dict) -> BatchPlugin:
        """Create and set up a fresh plugin instance from this entry."""
        instance = self.plugin_cls(siril,config)
        instance.set_up(
            key=self.key,
            title=self.title,
            items=self.items,
            columns=self.columns,
            config=plugin_config
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
        cls,
        spec: Union[str, dict, None] = None,
        *,
        key: Optional[str] = None,
        title: Optional[str] = None,
        items: Union[str, dict, list[PluginItem], None] = None,
        columns: int = 5,
        enabled: bool = True,
    ):
        """
        Class decorator: wraps a ``BatchPlugin`` subclass and registers its metadata.

        Normal use passes one YAML document that describes the whole plugin (see
        ``parse_plugin_spec``)::

            @BatchPluginRegistry.register(calibration_items)
            class CalibratePlugin(BatchPlugin): ...

        The YAML is parsed and validated right here, so a mistake is reported when the
        plugin module is loaded. The older keyword form
        ``register(key=..., title=..., items=..., columns=...)`` still works.
        """
        if spec is not None:
            plugin_spec = parse_plugin_spec(spec)
        elif key is not None:
            plugin_spec = PluginSpec(
                key=key,
                title=title if title is not None else key,
                items=parse_plugin_items(items, source=f"plugin '{key}'"),
                columns=columns,
                enabled=enabled,
            )
        else:
            raise TypeError(
                "register() needs a YAML plugin definition, e.g. "
                "@BatchPluginRegistry.register(calibration_items)"
            )

        def decorator(plugin_cls: Type[BatchPlugin]):
            cls._entries.append(
                BatchPluginEntry(
                    plugin_cls=plugin_cls,
                    key=plugin_spec.key,
                    title=plugin_spec.title,
                    items=plugin_spec.items,
                    columns=plugin_spec.columns,
                    enabled=plugin_spec.enabled,
                )
            )
            return plugin_cls

        return decorator

    @classmethod
    def all(cls) -> list[BatchPluginEntry]:
        """Return every registered plugin entry sorted by title."""
        return sorted(
            cls._entries,
            key=lambda entry: (entry.title or "").lower(),
        )

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
            print("Init plugin")
            plugin = entry.plugin_cls(self.siril, self.config)

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
        self.resize(900, 600)

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
            telescope["name"] for telescope in telescopes
        )

        selected = self.config.selected_telescope_name()
        index = self.telescope_combo.findText(selected)
        if index >= 0:
            self.telescope_combo.setCurrentIndex(index)

        def on_telescope_changed(self,name):
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
        try:
            spec = importlib.util.spec_from_file_location(file.stem, file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as error:  # e.g. a malformed YAML item definition
            print(f"Skipping plugin {file.name}: {error}")


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