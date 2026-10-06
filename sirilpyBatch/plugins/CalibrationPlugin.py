# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Nikolas Pommerening
# Contact: nikodemus.p@gmx.at
#
import os
import shutil
from dataclasses import dataclass, field
from typing import Callable, Optional

from PyQt6 import sip
from PyQt6.QtCore import QSettings, QTimer, Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sirilpy import LogColor # type: ignore
from sirilpyBatch import (
        BatchPlugin, 
        BatchPluginRegistry, 
        BatchCmd,
        PluginItem, 
        BatchContext,
        registerItem,
        scanDirectory
    )


Plugin_Config = """
Plugin:
    Key: calibrate
    Title: Prepare
Box:
    Columns: 6
Items:
    - LightsDir:
        Key: lights_dirs
        colspan: 6
        onChange: frame_dirs_changed
    - FrameTable:
        Key: lights_table
        colspan: 6
    - FrameDir:
        Key: frame_dirs
        colspan: 6
        onChange: frame_dirs_changed
    - FrameTable:
        Key: bias_table
        colspan: 6
    - FrameTable:
        Key: dark_table
        colspan: 6
    - FrameTable:
        Key: flat_table
        colspan: 6
    - separator
    - CheckBox:
        Key: cfa
        Label: CFA format
        Default: False
    - CheckBox:
        Key: equalize_cfa
        Label: equalize CFA
        Default: False
    - CheckBox:
        Key: debayer
        Label: Debayer
        Default: False
    - Separator
    - IntRange:
        Key: sigma
        Label: Sigma
        Default: 3,3
"""

# ------------------------------------------------------------------------------------------
@registerItem("framedir", "framedirs")
@dataclass
class FrameDirItem(PluginItem):
    """
    The "+ Frame-Dir" button (YAML type ``FrameDir``) for bias / dark / flat frames.
    ``LightsDirItem`` below is the same button for the light frames.

    A click opens a folder dialog and hands the chosen directory to the plugin, which loads
    the frames and distributes them to the tables by frame type.

    The item value (saved in the plugin config) is ``{"dirs": [...], "removed": [...]}``:
    the added directories and the files the user deleted from the tables. The callback
    (``onChange``) receives the same dict; after a click it also contains ``"rescan": [dir]``.
    """
    button_text: str = "+ Frame-Dir"
    dialog_title: str = "Select frame directory"

    # shared with the directory fields of PluginItem.py so both remember the same folder
    _SETTINGS = ("sirilpyBatch", "sirilpyBatch")  # organisation, application
    _LAST_KEY = "DirectoryItem/lastDirectory"
    REMEMBER_PARENT = True  # start the next dialog in the parent of the last choice

    @staticmethod
    def parse_state(value) -> dict:
        """Normalise a config/callback value to ``{"dirs": [str], "removed": [str]}``."""
        dirs, removed = [], []
        if isinstance(value, dict):
            dirs, removed = value.get("dirs") or [], value.get("removed") or []
        elif isinstance(value, (list, tuple)):
            dirs = value
        elif isinstance(value, str) and value.strip():
            dirs = [value]
        return {"dirs": [str(d) for d in dirs], "removed": [str(r) for r in removed]}

    @staticmethod
    def is_under(file: str, directory: str) -> bool:
        base = os.path.normcase(os.path.normpath(directory)).rstrip(os.sep) + os.sep
        return os.path.normcase(os.path.normpath(file)).startswith(base)

    @classmethod
    def last_directory(cls) -> str:
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
        widget.button = QPushButton(self.button_text)
        layout.addWidget(widget.button)
        layout.addStretch(1)
        widget.state = {"dirs": [], "removed": []}
        widget.notify = None  # the box's change handler, set in bind_widget
        return widget

    def bind_widget(self, widget, callback):
        widget.notify = callback
        widget.button.clicked.connect(lambda _checked=False: self._browse(widget))

    def _browse(self, widget):
        start = self.last_directory() or os.path.expanduser("~")
        path = QFileDialog.getExistingDirectory(widget, self.dialog_title, start)
        if not path:  # dialog cancelled
            return
        self.remember_directory(path)

        state = self.parse_state(getattr(widget, "state", None))
        if path not in state["dirs"]:
            state["dirs"].append(path)
        # adding a directory again brings back the files that were deleted from it
        state["removed"] = [r for r in state["removed"] if not self.is_under(r, path)]
        self.store(widget, state)

        notify = getattr(widget, "notify", None) or self.callback
        if notify:
            notify({**state, "rescan": [path]}, self.key)

    def store(self, widget, value):
        """Set the value without notifying anybody."""
        widget.state = self.parse_state(value)
        dirs = widget.state["dirs"]
        widget.button.setToolTip("\n".join(dirs) if dirs else self.dialog_title)

    def get_value(self, widget):
        state = self.parse_state(getattr(widget, "state", None))
        return state

    def set_value(self, widget, value):
        """Config restore: set the value and tell the plugin to load the directories."""
        self.store(widget, value)
        notify = getattr(widget, "notify", None) or self.callback
        if notify:
            notify(self.parse_state(widget.state), self.key)


@registerItem("lightsdir")
@dataclass
class LightsDirItem(FrameDirItem):
    """The "+ Lights-Dir" button (YAML type ``LightsDir``): same behaviour, for the light frames."""
    button_text: str = "+ Lights-Dir"
    dialog_title: str = "Select lights directory"


# ------------------------------------------------------------------------------------------
@registerItem("frametable")
@dataclass
class FrameTableItem(PluginItem):
    """
    Table filled by this plugin (YAML type ``FrameTable``), with a title and a Delete button.

    Fill it with ``item.set_value(widget, rows)``. Each row is a sequence of cell values or
    a dict ``{"cells": [...], "selected": bool, "highlight": bool, "marker": str, "tooltip": str}``.
    The selected row is drawn green, highlighted rows are bold, the marker is put in front of
    the first cell. Clicking a row calls ``on_select(row)``; the Delete menu calls
    ``on_delete("selected" | "all")``. Not saved in the plugin config.
    """
    columns: list[str] = field(
        default_factory=lambda: ["File", "Pixel", "Stacks", "Exposure [s]", "ISO"]
    )
    title: str = ""  # default: derived from the key (lights_table -> Lights)
    max_rows: int = 6  # visible rows before the table starts to scroll
    save: bool = False  # display-only, never stored in the plugin config
    on_select: Optional[Callable] = field(default=None, repr=False, compare=False)
    on_delete: Optional[Callable] = field(default=None, repr=False, compare=False)

    SELECTED_BG = "#2e7d32"
    SELECTED_FG = "#ffffff"
    TITLES = {"lights": "Lights", "bias": "Bias", "dark": "Darks", "flat": "Flats"}

    def _title(self) -> str:
        if self.title:
            return self.title
        base = (self.key or "").removesuffix("_table")
        return self.TITLES.get(base, base.replace("_", " ").title())

    def _fit_height(self, table: QTableWidget, row_count: int):
        rows = max(1, min(row_count, int(self.max_rows)))
        table.setFixedHeight(
            table.horizontalHeader().sizeHint().height()
            + rows * table.verticalHeader().defaultSectionSize()
            + 2 * table.frameWidth()
        )
        table.updateGeometry()

    def _cell_clicked(self, row: int, _column: int):
        if self.on_select is not None:
            self.on_select(row)

    def _delete(self, mode: str):
        if self.on_delete is not None:
            self.on_delete(mode)

    def create_widget(self, context: Optional[BatchContext] = None) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        title = QLabel(self._title())
        font = title.font()
        font.setBold(True)
        title.setFont(font)

        button = QPushButton("Delete")
        menu = QMenu(button)
        delete_selected = menu.addAction("Delete selected")
        delete_all = menu.addAction("Delete all")
        delete_selected.triggered.connect(lambda _checked=False: self._delete("selected"))
        delete_all.triggered.connect(lambda _checked=False: self._delete("all"))
        button.setMenu(menu)
        button.setEnabled(False)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(button)
        layout.addLayout(header)

        table = QTableWidget(0, len(self.columns))
        table.setHorizontalHeaderLabels([str(c) for c in self.columns])
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.cellClicked.connect(self._cell_clicked)
        self._fit_height(table, 0)
        layout.addWidget(table)

        container.table = table
        container.delete_button = button
        container.delete_selected = delete_selected
        container.delete_all = delete_all
        return container

    def bind_widget(self, widget, callback):
        pass

    def get_value(self, widget):
        return None

    def set_value(self, widget, value):
        table = getattr(widget, "table", widget)
        rows = list(value or [])
        table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            if isinstance(row, dict):
                cells, highlight = row.get("cells", []), bool(row.get("highlight"))
                marker, selected = row.get("marker") or "", bool(row.get("selected"))
                tooltip = row.get("tooltip")
            else:
                cells, highlight, marker, selected, tooltip = row, False, "", False, None
            for c, cell in enumerate(cells):
                text = (f"{marker} " if marker and c == 0 else "") + str(cell)
                entry = QTableWidgetItem(text)
                entry.setFlags(Qt.ItemFlag.ItemIsEnabled)
                if highlight or selected:
                    font = entry.font()
                    font.setBold(True)
                    entry.setFont(font)
                if selected:
                    entry.setBackground(QBrush(QColor(self.SELECTED_BG)))
                    entry.setForeground(QBrush(QColor(self.SELECTED_FG)))
                if tooltip:
                    entry.setToolTip(tooltip)
                table.setItem(r, c, entry)
        self._fit_height(table, len(rows))

        if hasattr(widget, "delete_button"):
            has_selection = any(isinstance(r, dict) and r.get("selected") for r in rows)
            widget.delete_button.setEnabled(bool(rows))
            widget.delete_selected.setEnabled(has_selection)
            widget.delete_all.setEnabled(bool(rows))


# ------------------------------------------------------------------------------------------
def _fits_header(path: str) -> dict:
    """Integer values of NAXIS1/NAXIS2/STACKCNT/NCOMBINE from the primary FITS header ({} if
    the file isn't a readable FITS file)."""
    path = os.fspath(path)
    if not path.lower().endswith((".fit", ".fits", ".fts")):
        return {}
    wanted = ("NAXIS1", "NAXIS2", "STACKCNT", "NCOMBINE")
    values = {}
    try:
        with open(path, "rb") as handle:
            for _ in range(64):  # header blocks of 2880 bytes
                block = handle.read(2880)
                if len(block) < 2880:
                    return values
                for i in range(0, 2880, 80):
                    card = block[i:i + 80].decode("ascii", "ignore")
                    name = card[:8].strip()
                    if name == "END":
                        return values
                    if name in wanted and card[8:10] == "= ":
                        try:
                            values[name] = int(float(card[10:].split("/")[0].strip()))
                        except ValueError:
                            pass
    except OSError:
        return {}
    return values


# Must come after the item registration above: the registry parses the YAML here.
@BatchPluginRegistry.register(Plugin_Config)
class CalibratePlugin(BatchPlugin):

    result_name = "calibration"

    # ── Frame loading ──────────────────────────────────────
    # Two directory buttons: the lights button only fills the Lights table, the frame button
    # distributes bias / dark / flat frames to their tables by frame type.
    DIR_KEYS = {"lights": "lights_dirs", "frames": "frame_dirs"}  # group -> item key
    GROUP_OF_KEY = {key: group for group, key in DIR_KEYS.items()}
    GROUPS = ("lights", "frames")
    CALIBRATION_KEYS = ("bias", "dark", "flat")
    SCAN_KEYS = ("lights", "bias", "dark", "flat")  # order of the tables
    SCAN_DELAY_MS = 600  # retry delay while the plugin box doesn't exist yet (config restore)

    EXPECTED_FRAME = {"lights": "light", "bias": "bias", "dark": "dark", "flat": "flat"}
    # The frame type is taken from the header; the first keyword found in it decides.
    # "dark" comes before "flat" so that "dark flat" frames count as darks.
    TYPE_KEYWORDS = (
        ("bias", "bias"), ("offset", "bias"),
        ("dark", "dark"), ("flat", "flat"),
        ("light", "lights"), ("object", "lights"), ("science", "lights"),
    )
    # Files without any frame-type keyword: in a lights directory they count as lights; in a
    # frame directory they are sorted by the name of their folder (e.g. ".../Darks/") and
    # ignored if that tells nothing. True -> files without a frame type are always ignored.
    STRICT_FRAME_TYPE = False

    # Which light properties a calibration frame has to match:
    #   dark -> exposure + ISO, bias -> ISO, flat -> ISO (flat exposure may differ)
    # The pixel size (width x height) always has to match, if it is known.
    MATCH_RULES = {
        "dark": ("pixel", "exposure", "iso"),
        "bias": ("pixel", "iso"),
        "flat": ("pixel", "iso"),
    }

    MAX_TOOLTIP_FILES = 30
    NO_CHOICE = "none"  # user clicked the selected row again: calibrate without

    @staticmethod
    def _show(value) -> str:
        return "n/a" if value is None else f"{value:g}"

    @staticmethod
    def _show_pixel(pixel) -> str:
        return "n/a" if not pixel else f"{pixel[0]} x {pixel[1]}"

    @staticmethod
    def _sort_key(combo):
        exposure, iso, pixel = combo
        return (exposure is None, exposure or 0, iso is None, iso or 0, pixel is None, pixel or (0, 0))

    def _header(self, frame) -> dict:
        path = os.fspath(frame.path)
        if path not in self._header_cache:
            try:
                self._header_cache[path] = _fits_header(path)
            except Exception:
                self._header_cache[path] = {}
        return self._header_cache[path]

    def _frame_pixels(self, frame):
        """(width, height) of a frame: from the scan result if it provides it, else the FITS header."""
        try:
            width, height = getattr(frame, "width", None), getattr(frame, "height", None)
            if width and height:
                return (int(width), int(height))
            for name in ("pixels", "size", "dimensions"):
                value = getattr(frame, name, None)
                if isinstance(value, (tuple, list)) and len(value) == 2 and all(value):
                    return (int(value[0]), int(value[1]))
            header = self._header(frame)
            if header.get("NAXIS1") and header.get("NAXIS2"):
                return (header["NAXIS1"], header["NAXIS2"])
        except Exception:
            pass  # unknown pixel size must never prevent the file from being listed
        return None

    def _frame_stack_count(self, frame) -> int:
        """Number of frames stacked into this file (STACKCNT in the FITS header of a master); 1 if unknown."""
        try:
            for name in ("stackcnt", "stack_count", "stackCount"):
                value = getattr(frame, name, None)
                if isinstance(value, int) and value > 0:
                    return value
            header = self._header(frame)
            return max(1, header.get("STACKCNT") or header.get("NCOMBINE") or 1)
        except Exception:
            return 1

    def _stack_total(self, key, files) -> int:
        """Stacks column: lights count files; bias/dark/flat add up the STACKCNT of their files."""
        if key == "lights":
            return len(files)
        return sum(self._stackcnt.get(f, 1) for f in files)

    def _init_state(self):
        if not hasattr(self, "_scans"):
            self._scans = {}        # key -> {(exposure, iso, pixel): [file paths]}
            self._raw = {}          # directory -> frames found in it
            self._choice = {}       # key -> combo picked by the user (or NO_CHOICE)
            self._selected = {}     # key -> selected combo (used for processing) or None
            self._row_combos = {}   # key -> combos in table row order
            self._header_cache = {}  # path -> FITS header values (see _fits_header)
            self._stackcnt = {}     # path -> number of frames stacked into that file
            self._dirs = {g: [] for g in self.GROUPS}          # group -> added directories
            self._removed = {g: set() for g in self.GROUPS}    # group -> files deleted from the tables
            self._load_tries = 0
            self.matches = {}       # key -> file paths of the selected group

    def _box_alive(self) -> bool:
        """True if the plugin box exists and its Qt object has not been deleted."""
        box = getattr(self, "box", None)
        return box is not None and not sip.isdeleted(box)

    # ── Directories ────────────────────────────────────────
    def frame_dirs_changed(self, value, key):
        """onChange handler of "+ Lights-Dir" / "+ Frame-Dir" (also called when the config is restored)."""
        self._init_state()
        group = self.GROUP_OF_KEY.get(key)
        if group is None:
            return
        state = FrameDirItem.parse_state(value)
        rescan = list(value.get("rescan") or []) if isinstance(value, dict) else []
        if (
            not rescan
            and state["dirs"] == self._dirs[group]
            and set(state["removed"]) == self._removed[group]
            and all(d in self._raw for d in state["dirs"])
        ):
            return  # echo of our own _store_state()
        self._dirs[group], self._removed[group] = list(state["dirs"]), set(state["removed"])
        for directory in rescan:
            self._raw.pop(directory, None)  # force a fresh scan of the added directory
        self._load_tries = 0
        QTimer.singleShot(0 if self._box_alive() else self.SCAN_DELAY_MS, self._load_frames)

    def _load_frames(self):
        """Scan the directories that are not scanned yet and refresh the tables."""
        if getattr(self, "box", None) is None:
            # config restored before the box exists: try again shortly
            if self._load_tries < 20:
                self._load_tries += 1
                QTimer.singleShot(self.SCAN_DELAY_MS, self._load_frames)
            return
        if not self._box_alive():
            return  # box was destroyed (e.g. rebuilt), nothing to update
        try:
            fresh = [(g, d) for g in self.GROUPS for d in self._dirs[g] if d not in self._raw]
            for directory in dict.fromkeys(d for _group, d in fresh):  # a directory may be in both groups
                self._scan_dir(directory)
            for group, directory in fresh:
                self._log_dir(group, directory)
            self._rebuild_scans(log_matches=True, reset_choice=True)
        except Exception as exc:
            self.context.siril.log(f"[frames] loading failed: {exc!r}", LogColor.RED)

    def _store_state(self, group):
        """Write dirs/removed back into the directory item so they are saved with the config."""
        if not self._box_alive():
            return
        item_key = self.DIR_KEYS[group]
        widget = self.box.widgets.get(item_key)
        item = self.box.item_by_key.get(item_key)
        if widget is None or item is None or sip.isdeleted(widget):
            return
        state = {"dirs": list(self._dirs[group]), "removed": sorted(self._removed[group])}
        item.store(widget, state)
        notify = getattr(widget, "notify", None)
        if notify:  # lets the box save the config; frame_dirs_changed ignores the echo
            try:
                notify(state, item_key)
            except Exception:
                pass

    def _resolve(self, directory) -> str:
        path = (directory or "").strip()
        if path and not os.path.isabs(path):
            path = os.path.join(self.get_siril_wd(), path)
        return path

    def _type_key(self, text):
        """Table key for a frame-type / folder-name text, or None."""
        text = str(text).lower()
        for word, key in self.TYPE_KEYWORDS:
            if word in text:
                return key
        return None

    def _target(self, frame, group):
        """
        (table key or None, label) for a frame found through the "lights" or "frames" button.

        The lights button only takes light frames, the frame button only bias/dark/flat;
        everything else is ignored (None).
        """
        frame_type = frame.frame_type
        if frame_type is None or not str(frame_type).strip():
            if self.STRICT_FRAME_TYPE:
                return None, "unknown"
            if group == "lights":
                return "lights", "unknown"
            folder = os.path.basename(os.path.dirname(os.fspath(frame.path)))
            key, label = self._type_key(folder), "unknown"
        else:
            key, label = self._type_key(frame_type), str(frame_type)
        if group == "lights":
            return ("lights" if key == "lights" else None), label
        return (key if key in self.CALIBRATION_KEYS else None), label

    def _scan_dir(self, directory, log=True):
        unreadable: list = []
        self._raw[directory] = list(
            scanDirectory(self._resolve(directory), on_error=lambda file, exc: unreadable.append(file))
        )
        if unreadable and log:
            self.context.siril.log(
                f"[frames] {directory}: {len(unreadable)} file(s) could not be read", LogColor.RED
            )

    def _log_dir(self, group, directory):
        """Log what a newly added directory contributed."""
        counts: dict = {}
        ignored: dict = {}
        frames = self._raw.get(directory, [])
        for frame in frames:
            target, label = self._target(frame, group)
            if target is None:
                ignored[label] = ignored.get(label, 0) + 1
            else:
                name = self.EXPECTED_FRAME[target]
                counts[name] = counts.get(name, 0) + 1
        parts = [f"{n} {name}" for name, n in sorted(counts.items())]
        if ignored:
            parts.append("ignored " + ", ".join(f"{n}x {label}" for label, n in sorted(ignored.items())))
        details = ", ".join(parts) or "no frames found"
        self.context.siril.log(
            f"[{group}] {directory}: {details}", LogColor.GREEN if counts else LogColor.SALMON
        )

    def _rebuild_scans(self, log_matches=True, reset_choice=True):
        """Distribute the loaded frames (minus the deleted ones) to the tables by frame type."""
        new = {key: {} for key in self.SCAN_KEYS}
        seen = set()

        for group in self.GROUPS:
            for directory in self._dirs[group]:
                for frame in self._raw.get(directory, []):
                    path = os.fspath(frame.path)
                    if path in self._removed[group]:
                        continue
                    target, _label = self._target(frame, group)
                    if target is None or (target, path) in seen:
                        continue
                    seen.add((target, path))
                    if target != "lights":
                        self._stackcnt[path] = self._frame_stack_count(frame)
                    combo = (frame.exposure, frame.iso, self._frame_pixels(frame))
                    new[target].setdefault(combo, []).append(path)

        old, self._scans = self._scans, new
        changed = [key for key in self.SCAN_KEYS if old.get(key) != new[key]]
        for key in self.SCAN_KEYS:
            chosen = self._choice.get(key)
            if chosen is None:
                continue
            if (reset_choice and key in changed) or (chosen != self.NO_CHOICE and chosen not in new[key]):
                del self._choice[key]

        # a changed lights table changes the suggestions of all other tables
        if not log_matches:
            log_keys = ()
        elif "lights" in changed:
            log_keys = self.SCAN_KEYS
        else:
            log_keys = tuple(changed)
        self._refresh_tables(log_keys=log_keys)

    def _on_delete(self, key, mode):
        """Delete menu of a table: remove the selected group or all groups from the list."""
        scan = self._scans.get(key, {})
        if mode == "selected":
            combo = self._selected.get(key)
            files = list(scan.get(combo, [])) if combo else []
        else:
            files = [f for group_files in scan.values() for f in group_files]
        if not files:
            return
        group = "lights" if key == "lights" else "frames"
        self._removed[group].update(files)
        self._choice.pop(key, None)
        self.context.siril.log(f"[{key}] removed {len(files)} file(s) from the list", LogColor.SALMON)
        self._store_state(group)
        self._rebuild_scans(log_matches=False, reset_choice=True)

    def _on_select(self, key, row):
        """The user clicked a row: select that group (deferred, the table is still handling the
        click). Clicking the selected row of bias/dark/flat again means "calibrate without"."""
        combos = self._row_combos.get(key, [])
        if row >= len(combos):
            return
        combo = combos[row]
        if key != "lights" and self._selected.get(key) == combo:
            self._choice[key] = self.NO_CHOICE
        else:
            self._choice[key] = combo
        QTimer.singleShot(0, self._refresh_tables)

    @staticmethod
    def _distance(combo, light) -> tuple:
        """How far a calibration group is from a light group: (pixel, ISO, exposure difference)."""
        (exposure, iso, pixel), (light_exposure, light_iso, light_pixel) = combo, light
        # unknown pixel size can't be compared, so it is treated as matching
        pixel_diff = 0 if pixel is None or light_pixel is None or pixel == light_pixel else 1
        # ISO is lenient: cameras that don't write an ISO value can't be compared by it
        iso_diff = 0 if None in (iso, light_iso) else abs(iso - light_iso)
        if None in (exposure, light_exposure):
            exposure_diff = 0 if exposure == light_exposure else float("inf")
        else:
            exposure_diff = abs(exposure - light_exposure)
        return (pixel_diff, iso_diff, exposure_diff)

    def _is_exact(self, key, combo, light) -> bool:
        """Does a calibration group satisfy the match rule of ``key`` for this light group?"""
        pixel_diff, iso_diff, exposure_diff = self._distance(combo, light)
        rule = self.MATCH_RULES.get(key, ())
        return not (
            ("pixel" in rule and pixel_diff)
            or ("iso" in rule and iso_diff)
            or ("exposure" in rule and exposure_diff)
        )

    def _select(self, key, scan, light_combos):
        """
        Pick the calibration groups for every light group.

        Per light group: all exact matches; if there are none, the single closest group,
        ranked by pixel size, then ISO difference, then exposure difference.
        Returns (exact groups, {light group: closest group} for lights without exact match).
        """
        exact, closest = set(), {}
        ordered = sorted(scan, key=self._sort_key)  # deterministic tie-break
        for light in sorted(light_combos, key=self._sort_key):
            hits = [c for c in ordered if self._is_exact(key, c, light)]
            if hits:
                exact.update(hits)
            elif ordered:
                closest[light] = min(ordered, key=lambda c: self._distance(c, light))
        return exact, closest

    def _describe(self, combo) -> str:
        return f"{self._show(combo[0])} s / ISO {self._show(combo[1])} / {self._show_pixel(combo[2])}"

    def _file_label(self, files) -> str:
        first = os.path.basename(files[0])
        return first if len(files) == 1 else f"{first} (+{len(files) - 1})"

    def _tooltip(self, files) -> str:
        names = [os.path.basename(f) for f in files]
        text = "\n".join(names[:self.MAX_TOOLTIP_FILES])
        if len(names) > self.MAX_TOOLTIP_FILES:
            text += f"\n... (+{len(names) - self.MAX_TOOLTIP_FILES} more)"
        return text

    def _refresh_tables(self, log_keys=()):
        siril = self.context.siril
        light = None  # selected light group, the others are matched against it

        for key in self.SCAN_KEYS:  # "lights" comes first, the others depend on its selection
            scan = self._scans.get(key, {})
            ordered = sorted(scan, key=self._sort_key)

            # system suggestion: lights -> the largest group; others -> best match for the light
            if key == "lights":
                suggestion = max(ordered, key=lambda c: len(scan[c])) if ordered else None
                is_exact = True
            else:
                exact, closest = self._select(key, scan, [light] if light else [])
                is_exact = bool(exact)
                if exact:
                    suggestion = max(sorted(exact, key=self._sort_key),
                                     key=lambda c: self._stack_total(key, scan[c]))
                else:
                    suggestion = closest.get(light)

            chosen = self._choice.get(key)
            if chosen == self.NO_CHOICE:
                selected = None
            elif chosen is not None and chosen in scan:
                selected = chosen
            else:
                selected = suggestion
            self._selected[key] = selected
            self._row_combos[key] = ordered
            if key == "lights":
                light = selected

            rows = []
            for combo in ordered:
                files = scan[combo]
                rows.append({
                    "cells": [
                        self._file_label(files),
                        self._show_pixel(combo[2]),
                        self._stack_total(key, files),
                        self._show(combo[0]),
                        self._show(combo[1]),
                    ],
                    "selected": combo == selected,
                    "highlight": combo == suggestion,
                    "marker": "\u2248" if combo == suggestion and not is_exact else "",
                    "tooltip": self._tooltip(files),
                })
            self.matches[key] = list(scan[selected]) if selected else []
            self._set_table(key, rows)

            if key == "lights" or key not in log_keys or not scan or not light or not suggestion:
                continue
            if is_exact:
                siril.log(
                    f"[{key}] suggested: {self._describe(suggestion)} ({len(scan[suggestion])} file(s))",
                    LogColor.GREEN,
                )
            else:
                siril.log(
                    f"[{key}] no exact match for {self._describe(light)}; closest: "
                    f"{self._describe(suggestion)} ({len(scan[suggestion])} file(s))",
                    LogColor.SALMON,
                )

    def _set_table(self, key, rows):
        if not self._box_alive():
            return
        box = self.box
        table_key = f"{key}_table"
        widget, item = box.widgets.get(table_key), box.item_by_key.get(table_key)
        if widget is None or item is None or sip.isdeleted(widget):
            return
        item.on_select = lambda row, k=key: self._on_select(k, row)
        item.on_delete = lambda mode, k=key: self._on_delete(k, mode)
        try:
            item.set_value(widget, rows)
        except RuntimeError:
            pass  # widget was deleted in the meantime

    # ── Processing ─────────────────────────────────────────
    MAX_LOGGED_FILES = 20  # file names listed per type in the log

    @staticmethod
    def _p(path: str) -> str:
        """Siril-friendly path (forward slashes)."""
        return path.replace("\\", "/")

    def _q(self, path: str) -> str:
        """Quoted path for commands like ``cd``."""
        return f'"{self._p(path)}"'

    def _stage(self, files, directory) -> str:
        """Collect ``files`` in a fresh ``directory`` (symlink, else hardlink, else copy)."""
        shutil.rmtree(directory, ignore_errors=True)
        os.makedirs(directory)
        for src in files:
            dst = os.path.join(directory, os.path.basename(src))
            try:
                os.symlink(src, dst)
            except OSError:
                try:
                    os.link(src, dst)
                except OSError:
                    shutil.copy2(src, dst)
        return directory

    def _log_used(self, key, files, detail):
        names = [os.path.basename(f) for f in files]
        shown = ", ".join(names[:self.MAX_LOGGED_FILES])
        if len(names) > self.MAX_LOGGED_FILES:
            shown += f", ... (+{len(names) - self.MAX_LOGGED_FILES} more)"
        self.context.siril.log(f"[{key}] using {len(files)} file(s) [{detail}]: {shown}", LogColor.GREEN)

    def _plan_calibration(self):
        """
        Rescan all added directories and decide which files are used.

        Uses the green (selected) row of every table: the system suggestion unless the user
        clicked another row. Returns (light files, {'bias'|'dark'|'flat': files}).
        """
        siril = self.context.siril
        self._init_state()
        for group, item_key in self.DIR_KEYS.items():
            try:  # the saved item value is the source of truth (also without an open window)
                state = FrameDirItem.parse_state(self.get_value(item_key))
            except Exception:
                state = {"dirs": [], "removed": []}
            if state["dirs"]:
                self._dirs[group], self._removed[group] = list(state["dirs"]), set(state["removed"])
        if not self._dirs["lights"]:
            raise RuntimeError("no light directory, add one with '+ Lights-Dir'")
        for directory in dict.fromkeys(d for g in self.GROUPS for d in self._dirs[g]):
            self._scan_dir(directory, log=False)  # fresh scan: files may have changed on disk
        self._rebuild_scans(log_matches=False, reset_choice=False)

        lights = self._scans.get("lights", {})
        if not lights:
            raise RuntimeError("no light frames loaded, add the light directory with '+ Lights-Dir'")
        light = self._selected.get("lights")
        if light is None:
            raise RuntimeError("no light group selected, click a row in the Lights table")
        light_files = list(lights[light])
        self._log_used("lights", light_files, self._describe(light))

        selection = {}
        for key in ("bias", "dark", "flat"):
            scan = self._scans.get(key, {})
            if not scan:
                siril.log(f"[{key}] no files found, calibrating without {key}", LogColor.SALMON)
                continue
            combo = self._selected.get(key)
            if combo is None:
                siril.log(f"[{key}] nothing selected, calibrating without {key}", LogColor.SALMON)
                continue
            if light[2] and combo[2] and combo[2] != light[2]:
                siril.log(f"[{key}] {self._describe(combo)} has a different pixel size than the lights",
                          LogColor.SALMON)
            files = list(scan[combo])
            self._log_used(key, files, f"{self._describe(combo)}, {self._stack_total(key, files)} stacked frame(s)")
            selection[key] = files
        return light_files, selection

    def _build_master(self, key, files, proc, bias_master=None) -> str:
        """Stack ``files`` to ``<proc>/<key>_master`` and return its path (without extension)."""
        siril = self.context.siril
        if len(files) == 1:
            siril.log(f"[{key}] single file, used directly as master", LogColor.GREEN)
            return self._p(files[0])
        if len(files) < 3:
            siril.log(f"[{key}] only {len(files)} files, rejection stacking works best with 3 or more", LogColor.SALMON)

        src = self._stage(files, os.path.join(proc, f"src_{key}"))
        out = os.path.join(proc, key)
        shutil.rmtree(out, ignore_errors=True)
        os.makedirs(out)
        master = self._p(os.path.join(proc, f"{key}_master"))
        low, high = self.get_value("sigma")

        siril.log(f"[{key}] building master from {len(files)} files", LogColor.GREEN)
        self.cmd("cd", self._q(src)).run()
        self.cmd("convert", key).add_arg("-out={}", self._p(out)).run()
        self.cmd("cd", self._q(out)).run()
        if key == "flat":
            seq = key
            if bias_master:
                self.cmd("calibrate", key).add_arg("-bias={}", bias_master).run()
                seq = f"pp_{key}"
            self.cmd("stack", seq, "rej", str(low), str(high), "-norm=mul").add_arg("-out={}", master).run()
        else:
            self.cmd("stack", key, "rej", str(low), str(high), "-nonorm").add_arg("-out={}", master).run()
        return master

    def process(self):
        siril = self.context.siril
        light_files, selection = self._plan_calibration()

        # ── 0) process directory inside the work dir ──────────────
        proc = os.path.join(self.get_siril_wd(), "process")
        os.makedirs(proc, exist_ok=True)

        # ── 1) masters from the best matching bias / dark / flat ───
        masters = {}
        if "bias" in selection:
            masters["bias"] = self._build_master("bias", selection["bias"], proc)
        if "dark" in selection:
            masters["dark"] = self._build_master("dark", selection["dark"], proc)
        if "flat" in selection:
            masters["flat"] = self._build_master("flat", selection["flat"], proc, masters.get("bias"))

        # ── 2) Convert Lights => process dir ─────────────────────
        siril.log("[INFO] prepare light", LogColor.GREEN)
        src = self._stage(light_files, os.path.join(proc, "src_light"))
        self.cmd("cd", self._q(src)).run()
        self.cmd("convert", "light").add_arg("-out={}", self._p(proc)).run()
        self.cmd("cd", self._q(proc)).run()

        # ── 3) Calibrate the images ──────────────────────────────
        calibrate = self.cmd("calibrate", "light")
        for key in ("bias", "dark", "flat"):
            if key in masters:
                calibrate.add_arg(f"-{key}={{}}", masters[key])
        (
            calibrate
            .add_opt("-cfa", self.get_value("cfa"))
            .add_opt("-equalize_cfa", self.get_value("equalize_cfa"))
            .add_opt("-debayer", self.get_value("debayer"))
            .run()
        )
        # ── 4) register ─────────────────────────────
        self.cmd("register", "pp_light").run()
        # ── 5) stack the images ─────────────────────────────
        self.cmd("stack", "r_pp_light", "rej", "3", "3", "-norm=addscale", "-output_norm", "-rgb_equal", f"-out={self.result_name}").run()

    def load(self):
        wd = self.get_siril_wd()
        self.cmd("load", f"{wd}/process/{self.result_name}").run()