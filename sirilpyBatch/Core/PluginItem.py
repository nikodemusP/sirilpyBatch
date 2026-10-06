# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Nikolas Pommerening
# Contact: nikodemus.p@gmx.at
#
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Type

from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtWidgets import (
    QLineEdit,
    QSlider,
    QWidget,
    QHBoxLayout,
    QCheckBox,
    QDoubleSpinBox,
    QComboBox,
    QSpinBox,
    QPushButton,
    QFileDialog,
)
import os

from .BatchContext import BatchContext



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
    callback: Optional[Callable[[Any, str], None]] = None  # called as callback(value, key)
    # whenever this item's value changes (in addition to PluginBox.valueChanged)
    save: bool = True  # False: value is neither written to nor restored from the plugin config
    onChange: Optional[str] = None  # name of a method on the owning plugin (e.g. from YAML);
    # BatchPlugin.create_plugin_box resolves it and stores the bound method in ``callback``.



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
    def create_widget(self, context: Optional[BatchContext] = None):
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
class DirectoryItem(PluginItem):
    """Text field holding a directory path plus a button that opens a folder dialog."""
    dialog_title: str = "Select directory"
    button_text: str = "…"

    # The last chosen directory is remembered (also across sessions) so the next folder
    # dialog doesn't start from the home directory again.
    # REMEMBER_PARENT: start in the *parent* of the last choice, which shows the sibling
    # folders (Lights / Darks / Flats / Bias next to each other). False: start in the
    # chosen folder itself.
    REMEMBER_PARENT = True
    _SETTINGS = ("sirilpyBatch", "sirilpyBatch")  # organisation, application
    _LAST_KEY = "DirectoryItem/lastDirectory"

    @classmethod
    def last_directory(cls) -> str:
        """Start directory for the next dialog ('' if nothing usable is remembered)."""
        value = str(QSettings(*cls._SETTINGS).value(cls._LAST_KEY, "") or "")
        return value if os.path.isdir(value) else ""

    @classmethod
    def remember_directory(cls, path: str):
        folder = os.path.dirname(os.path.normpath(path)) if cls.REMEMBER_PARENT else path
        QSettings(*cls._SETTINGS).setValue(cls._LAST_KEY, folder)

    def create_widget(self, context: Optional[BatchContext] = None) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        widget.edit = QLineEdit()
        widget.button = QPushButton(self.button_text)
        widget.button.setToolTip(self.dialog_title)
        widget.button.setFixedWidth(30)

        resolved_default = resolve_config_value(self.default, context)
        if resolved_default is not None:
            widget.edit.setText(str(resolved_default))

        def browse():
            start = widget.edit.text().strip()
            if not os.path.isdir(start):
                start = self.last_directory() or os.path.expanduser("~")
            path = QFileDialog.getExistingDirectory(widget, self.dialog_title, start)
            if path:  # empty string means the dialog was cancelled
                widget.edit.setText(path)
                self.remember_directory(path)

        widget.button.clicked.connect(browse)

        layout.addWidget(widget.edit, 1)
        layout.addWidget(widget.button)
        return widget

    def bind_widget(self, widget, callback):
        widget.edit.textChanged.connect(
            lambda value, key=self.key: callback(value, key)
        )

    def get_value(self, widget):
        return widget.edit.text()

    def set_value(self, widget, value):
        widget.edit.setText("" if value is None else str(value))


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
class _RangeItem(PluginItem):
    """Shared base for a (low, high) pair of spin boxes."""
    minimum: float = 0
    maximum: float = 100
    step: float = 1

    _cast = int  # overridden by subclasses; converts raw values to the item's number type

    def __post_init__(self):
        # YAML gives us "0,2" (a string) or [0, 2] (a list); normalise to a tuple.
        if isinstance(self.default, str):
            self.default = [part.strip() for part in self.default.split(",")]
        if self.default is not None:
            try:
                low, high = self.default
                self.default = (self._cast(low), self._cast(high))
            except (TypeError, ValueError):
                raise ValueError(
                    f"{type(self).__name__} '{self.key}': default must be two numbers "
                    f"like '0,2' or [0, 2], got {self.default!r}"
                )

    def _make_spinbox(self) -> QWidget:
        raise NotImplementedError

    def create_widget(self, context: Optional[BatchContext] = None):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        min_val = self._cast(resolve_config_value(self.minimum, context))
        max_val = self._cast(resolve_config_value(self.maximum, context))

        resolved_default = resolve_config_value(self.default, context)
        if isinstance(resolved_default, str):
            resolved_default = [self._cast(part.strip()) for part in resolved_default.split(",")]

        low, high = resolved_default or (min_val, max_val)

        widget.low = self._make_spinbox()
        widget.high = self._make_spinbox()

        for spinbox, value in ((widget.low, low), (widget.high, high)):
            spinbox.setMinimum(min_val)
            spinbox.setMaximum(max_val)
            spinbox.setSingleStep(self._cast(self.step))
            spinbox.setValue(self._cast(value))
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
        widget.low.setValue(self._cast(low))
        widget.high.setValue(self._cast(high))


@dataclass
class IntRangeItem(_RangeItem):
    _cast = int

    def _make_spinbox(self):
        return QSpinBox()


@dataclass
class FloatRangeItem(_RangeItem):
    decimals: int = 2
    _cast = float

    def _make_spinbox(self):
        spinbox = QDoubleSpinBox()
        spinbox.setDecimals(int(self.decimals))
        return spinbox


ITEM_TYPES: dict[str, Type[PluginItem]] = {
    "checkbox": CheckboxItem,
    "separator": SeparatorItem,
    "seperator": SeparatorItem,  # common misspelling
    "combobox": ComboBoxItem,
    "combo": ComboBoxItem,
    "text": TextItem,
    "directory": DirectoryItem,
    "dir": DirectoryItem,
    "folder": DirectoryItem,
    "int": IntItem,
    "integer": IntItem,
    "float": FloatItem,
    "slider": SliderItem,
    "range": IntRangeItem,
    "intrange": IntRangeItem,
    "floatrange": FloatRangeItem,
}


def registerItem(*names: str):
    """
    Class decorator that makes a ``PluginItem`` subclass usable from a plugin's YAML.

    Lets a plugin ship its own item types instead of adding them to this file::

        @register_item("frametable")
        @dataclass
        class FrameTableItem(PluginItem): ...

    The YAML name is matched case-insensitively. Register *before* the plugin class is
    decorated with ``@BatchPluginRegistry.register`` so the type is known when the YAML
    is parsed.
    """
    def decorator(cls: Type[PluginItem]) -> Type[PluginItem]:
        for name in names:
            ITEM_TYPES[name.lower()] = cls
        return cls
    return decorator