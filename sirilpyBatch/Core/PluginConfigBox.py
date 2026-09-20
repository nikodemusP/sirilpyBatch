from copy import deepcopy
from typing import Any, Optional

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import (
    QSizePolicy,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QCheckBox,
    QGroupBox,
)

from .BatchContext import BatchContext
from .PluginItem import PluginItem, SeparatorItem

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