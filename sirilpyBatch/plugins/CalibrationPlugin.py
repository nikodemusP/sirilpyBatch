# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Nikolas Pommerening
# Contact: nikodemus.p@gmx.at
#
import os
import shutil
from dataclasses import dataclass, field
from typing import Optional

from PyQt6 import sip
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem, QWidget
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
    - Directory:
        Key: lights
        Label: Lights
        colspan: 6
        onChange: directory_entered
    - FrameTable:
        Key: lights_table
        colspan: 6
    - Directory:
        Key: bias
        Label: Bias
        colspan: 6
        onChange: directory_entered
    - FrameTable:
        Key: bias_table
        colspan: 6
    - Directory:
        Key: dark
        Label: Darks
        colspan: 6
        onChange: directory_entered
    - FrameTable:
        Key: dark_table
        colspan: 6
    - Directory:
        Key: flat
        Label: Flats
        colspan: 6
        onChange: directory_entered
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
@registerItem("frametable")
@dataclass
class FrameTableItem(PluginItem):
    """
    Read-only table filled by this plugin (YAML type ``FrameTable``).

    Fill it with ``item.set_value(widget, rows)``. Each row is a sequence of cell values or
    a dict ``{"cells": [...], "highlight": bool, "marker": str}``; highlighted rows are bold
    with a leading marker (default check mark). Not saved in the plugin config (save: false).
    """
    columns: list[str] = field(default_factory=lambda: ["Files", "Exposure [s]", "ISO"])
    max_rows: int = 6  # visible rows before the table starts to scroll
    save: bool = False  # display-only, never stored in the plugin config

    def _fit_height(self, table: QTableWidget, row_count: int):
        rows = max(1, min(row_count, int(self.max_rows)))
        table.setFixedHeight(
            table.horizontalHeader().sizeHint().height()
            + rows * table.verticalHeader().defaultSectionSize()
            + 2 * table.frameWidth()
        )
        table.updateGeometry()

    def create_widget(self, context: Optional[BatchContext] = None) -> QWidget:
        table = QTableWidget(0, len(self.columns))
        table.setHorizontalHeaderLabels([str(c) for c in self.columns])
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._fit_height(table, 0)
        return table

    def bind_widget(self, widget, callback):
        pass

    def get_value(self, widget):
        return None

    def set_value(self, widget, value):
        rows = list(value or [])
        widget.setRowCount(len(rows))
        for r, row in enumerate(rows):
            if isinstance(row, dict):
                cells, highlight = row.get("cells", []), bool(row.get("highlight"))
                marker = row.get("marker") or "\u2713"
            else:
                cells, highlight, marker = row, False, ""
            for c, cell in enumerate(cells):
                text = (f"{marker} " if highlight and c == 0 else "") + str(cell)
                entry = QTableWidgetItem(text)
                if highlight:
                    font = entry.font()
                    font.setBold(True)
                    entry.setFont(font)
                widget.setItem(r, c, entry)
        self._fit_height(widget, len(rows))


# Must come after the item registration above: the registry parses the YAML here.
@BatchPluginRegistry.register(Plugin_Config)
class CalibratePlugin(BatchPlugin):

    result_name = "calibration"

    # ── Directory analysis ─────────────────────────────────
    SCAN_KEYS = ("lights", "bias", "dark", "flat")  # order of the directory items
    SCAN_DELAY_MS = 600  # wait until typing has paused before scanning

    # Frame type each directory is expected to contain; files whose header says otherwise
    # are ignored (e.g. a stray light frame in the bias folder).
    EXPECTED_FRAME = {"lights": "light", "bias": "bias", "dark": "dark", "flat": "flat"}
    # Files without any frame-type keyword can't be classified. False: keep them,
    # True: ignore them too.
    STRICT_FRAME_TYPE = False

    # Which light properties a calibration frame has to match:
    #   dark -> exposure + ISO, bias -> ISO, flat -> ISO (flat exposure may differ)
    MATCH_RULES = {
        "dark": ("exposure", "iso"),
        "bias": ("iso",),
        "flat": ("iso",),
    }

    @staticmethod
    def _show(value) -> str:
        return "n/a" if value is None else f"{value:g}"

    @staticmethod
    def _sort_key(combo):
        exposure, iso = combo
        return (exposure is None, exposure or 0, iso is None, iso or 0)

    def _init_state(self):
        if not hasattr(self, "_scans"):
            self._scans = {}    # key -> {(exposure, iso): [file paths]}
            self._timers = {}   # key -> debounce QTimer
            self._pending = {}  # key -> latest entered path
            self.matches = {}   # key -> file paths matching the lights (bias/dark/flat)

    def directory_entered(self, value, key):
        """onChange handler: (re)start a short timer so we scan only after typing paused."""
        self._init_state()
        self._pending[key] = value
        timer = self._timers.get(key)
        if timer is None:
            timer = QTimer()
            timer.setSingleShot(True)
            timer.setInterval(self.SCAN_DELAY_MS)
            timer.timeout.connect(lambda k=key: self._on_scan_timer(k))
            self._timers[key] = timer
        timer.start()

    def _box_alive(self) -> bool:
        """True if the plugin box exists and its Qt object has not been deleted."""
        box = getattr(self, "box", None)
        return box is not None and not sip.isdeleted(box)

    def _on_scan_timer(self, key):
        # The box may have been rebuilt/destroyed while the debounce timer was running
        # (e.g. when all plugins are loaded into one window); then there is nothing to update.
        if getattr(self, "box", None) is not None and not self._box_alive():
            return
        self._scan_directory(key, self._pending.get(key, ""))

    def _scan_directory(self, key, path, log_matches=True):
        self._init_state()
        path = (path or "").strip()
        if path and not os.path.isabs(path):
            path = os.path.join(self.get_siril_wd(), path)

        unreadable: list = []
        frames = scanDirectory(path, on_error=lambda file, exc: unreadable.append(file))

        expected = self.EXPECTED_FRAME.get(key)
        scan: dict = {}     # (exposure, iso) -> [file paths]
        ignored: dict = {}  # other frame type -> number of skipped files
        for frame in frames:
            if expected and (
                frame.frame_type != expected if frame.frame_type is not None else self.STRICT_FRAME_TYPE
            ):
                label = frame.frame_type or "unknown"
                ignored[label] = ignored.get(label, 0) + 1
                continue
            scan.setdefault((frame.exposure, frame.iso), []).append(frame.path)

        siril = self.context.siril
        if ignored:
            details = ", ".join(f"{n}x {t}" for t, n in sorted(ignored.items()))
            siril.log(f"[{key}] ignored files of other frame types: {details}", LogColor.SALMON)
        if unreadable:
            siril.log(f"[{key}] {len(unreadable)} file(s) could not be read", LogColor.RED)

        self._scans[key] = scan
        # a changed lights directory changes the matches of all other directories
        log_keys = (self.SCAN_KEYS if key == "lights" else (key,)) if log_matches else ()
        self._refresh_tables(log_keys=log_keys)

    @staticmethod
    def _distance(combo, light) -> tuple:
        """How far a calibration group is from a light group: (ISO difference, exposure difference)."""
        (exposure, iso), (light_exposure, light_iso) = combo, light
        # ISO is lenient: cameras that don't write an ISO value can't be compared by it
        iso_diff = 0 if None in (iso, light_iso) else abs(iso - light_iso)
        if None in (exposure, light_exposure):
            exposure_diff = 0 if exposure == light_exposure else float("inf")
        else:
            exposure_diff = abs(exposure - light_exposure)
        return (iso_diff, exposure_diff)

    def _is_exact(self, key, combo, light) -> bool:
        """Does a calibration group satisfy the match rule of ``key`` for this light group?"""
        iso_diff, exposure_diff = self._distance(combo, light)
        rule = self.MATCH_RULES.get(key, ())
        return not (("iso" in rule and iso_diff) or ("exposure" in rule and exposure_diff))

    def _select(self, key, scan, light_combos):
        """
        Pick the calibration groups for every light group.

        Per light group: all exact matches; if there are none, the single closest group,
        ranked by ISO difference first, then exposure difference.
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
        return f"{self._show(combo[0])} s / ISO {self._show(combo[1])}"

    def _refresh_tables(self, log_keys=()):
        siril = self.context.siril
        light_combos = set(self._scans.get("lights", {}))

        for key in self.SCAN_KEYS:
            scan = self._scans.get(key, {})
            exact, closest = ({}, {}) if key == "lights" else self._select(key, scan, light_combos)
            approx = set(closest.values()) - set(exact)

            rows, matched_files = [], []
            for combo in sorted(scan, key=self._sort_key):
                files = scan[combo]
                marker = "\u2713" if combo in exact else "\u2248" if combo in approx else ""
                rows.append({
                    "cells": [len(files), self._show(combo[0]), self._show(combo[1])],
                    "highlight": bool(marker),
                    "marker": marker,
                })
                if marker:
                    matched_files.extend(files)
            self.matches[key] = matched_files
            self._set_table(key, rows)

            if key == "lights" or key not in log_keys or not scan or not light_combos:
                continue
            if exact:
                count = sum(len(scan[c]) for c in exact)
                siril.log(f"[{key}] {count} matching file(s) for the lights", LogColor.GREEN)
            for light, combo in closest.items():
                siril.log(
                    f"[{key}] no exact match for {self._describe(light)}; closest: "
                    f"{self._describe(combo)} ({len(scan[combo])} file(s))",
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
        Rescan all directories and decide which files are used.

        Returns (light files, {'bias'|'dark'|'flat': files}). Only the largest light group
        (same exposure/ISO) is processed, because one set of masters is used for all lights.
        """
        siril = self.context.siril
        for key in self.SCAN_KEYS:
            self._scan_directory(key, self.get_value(key), log_matches=False)

        lights = self._scans.get("lights", {})
        if not lights:
            raise RuntimeError("no light frames found, check the Lights directory")

        primary = max(sorted(lights, key=self._sort_key), key=lambda c: len(lights[c]))
        skipped = [c for c in lights if c != primary]
        if skipped:
            siril.log(
                f"[lights] several exposure/ISO groups found; processing only the largest "
                f"({self._describe(primary)}), skipping: "
                + ", ".join(f"{len(lights[c])}x {self._describe(c)}" for c in skipped),
                LogColor.SALMON,
            )
        light_files = lights[primary]
        self._log_used("lights", light_files, self._describe(primary))

        selection = {}
        for key in ("bias", "dark", "flat"):
            scan = self._scans.get(key, {})
            if not scan:
                siril.log(f"[{key}] no files found, calibrating without {key}", LogColor.SALMON)
                continue
            exact, closest = self._select(key, scan, [primary])
            combos = sorted(exact or closest.values(), key=self._sort_key)
            files = [f for c in combos for f in scan[c]]
            detail = ", ".join(self._describe(c) for c in combos) + ("" if exact else ", closest match")
            self._log_used(key, files, detail)
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
