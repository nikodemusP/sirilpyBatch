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

        self.cmd("cd","process").run()

        if self.get_value("plade"):
            self.cmd("platesolve").run()

        if self.get_value("pcc"):
            self.pcc()

        if self.get_value("spcc"):
            self.spcc()

        self.cmd("save","result_calibration")

    def pcc(self):
        (
            self.cmd("pcc")
            .add_arg("-catalog={}",self.get_value("pcc_catalogue"))
            .add_arg("-bgtol={},{}",self.get_value("pcc_bgtol"))
            .run()
        )


    def spcc(self):
        filterCfg = self.get_config(f"filterCfg.{filter}",'-oscfilter=No filter')
        (
            self.cmd("spcc")
            .add_arg("-oscsensor={}",self.get_config("telescope.sensor",""))
            .add_arg("{}",filterCfg)
            .add_arg("-bgtol={},{}",self.get_value("spcc_bgtol"))
            .run()
        )

    def load(self):
        wd = self.get_siril_wd()
        self.cmd("load", f"{wd}/process/{self.result_name}")