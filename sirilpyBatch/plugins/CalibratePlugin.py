# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Nikolas Pommerening
# Contact: nikodemus.p@gmx.at
#
from sirilpy import LogColor # type: ignore
from sirilpyBatch import BatchPlugin, BatchPluginRegistry, BatchCmd


Plugin_Config = """
Plugin:
    Key: calibrate
    Title: Prepare
Box:
    Columns: 6
Items:
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

@BatchPluginRegistry.register(Plugin_Config)
class CalibratePlugin(BatchPlugin):

    result_name = "calibration"

    def process(self):
        # ── 1) Convert Lights ─────────────────────────────
        self.context.siril.log(f"[INFO] prepare light", LogColor.GREEN)
        self.cmd("cd","lights").run()
        self.cmd("convert","light","-out=../process").run()
        self.cmd("cd","../process").run()

        # ── 2) Calibrate the images ─────────────────────────────
        (
            self.cmd("calibrate","light","-bias=../masters/bias_master","-dark=../masters/dark_master","-flat=../masters/flat_master")
            .add_opt("-cfa",self.get_value("cfa"))
            .add_opt("-equalize_cfa",self.get_value("equalize_cfa"))
            .add_opt("-debayer",self.get_value("debayer"))
            .run()
        )
        # ── 2) register ─────────────────────────────
        self.cmd("register","pp_light").run()
        # ── 3) stack the images ─────────────────────────────
        self.cmd("stack","r_pp_light","rej","3","3","-norm=addscale","-output_norm","-rgb_equal",f"-out={self.result_name}").run()

    def load(self):
        wd = self.get_siril_wd()
        self.cmd("load", f"{wd}/process/{self.result_name}").run()
