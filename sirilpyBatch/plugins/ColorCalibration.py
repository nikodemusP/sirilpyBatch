# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Nikolas Pommerening
# Contact: nikodemus.p@gmx.at
#
from sirilpy import LogColor # type: ignore
from sirilpyBatch import BatchPlugin, BatchPluginRegistry 

Plugin_Config = """
Plugin:
    Key: color_calibration
    Title: Color Calibration
Box:
    Columns: 6
Items:
    - CheckBox:
        Key: plade
        Label: Pladesolve
        Default: True
    - Separator
    - CheckBox:
        Key: pcc
        Label: Photometric Color Calibration
        Default: False
    - Separator
    - ComboBox:
        Key: pcc_catalogue
        Label: Catalogue
        Values: ["none", "apass", "localgaia", "gaia", "nomad"]
        Default: gaia
    - IntRange:
        Key: pcc_bgtol
        Label: Tolerance
        Default: 0,2
    - Separator
    - CheckBox:
        Key: spcc
        Label: Spectrophotometric Color Calibration
        Default: False
    - Separator
    - ComboBox:
        Key: spcc_filter
        Label: Filter
        Values: "@telescope.filter"
        Default: No Filter
    - FloatRange:
        Key: spcc_bgtol
        Label: Tolerance
        Default: [2.0,2.8]
        Step: 0.1
"""


@BatchPluginRegistry.register(Plugin_Config)
class CalibratePlugin(BatchPlugin):

    result_name = "calibration"

    def process(self):
        # ── 1) Convert Lights ─────────────────────────────
        self.context.siril.log(f"[INFO] plade solve", LogColor.GREEN)

        self.cmd("cd","process")
        if self.get_value("plade"):
            self.cmd("platesolve")
        if self.get_value("pcc"):
            self.pcc()
        if self.get_value("spcc"):
            self.spcc()
        self.cmd("save","result_calibration")

    def pcc(self):
        args = ["pcc"]
        low, high = self.get_value("pcc_bgtol")
        catalog = self.get_value("pcc_catalogue")

        if catalog != "none":
            args.append(f"-catalog={catalog}")
        else:
            args.append(f"-bgtol={low},{high}")
        self.cmd(*args)

    def spcc(self):
        filter = self.get_value("spcc_filter")
        low, high = self.get_value("spcc_bgtol")
        sensor = self.get_config("telescope.sensor","")
        filterCfg = self.get_config(f"filterCfg.{filter}",'-oscfilter="No filter"')
        self.cmd("spcc",
                 f"\"-oscsensor={sensor}\"",
                 f"\"{filterCfg}\"",
                 f"\"-bgtol={low},{high}\"")

    def load(self):
        wd = self.get_siril_wd()
        self.cmd("load", f"{wd}/process/{self.result_name}")