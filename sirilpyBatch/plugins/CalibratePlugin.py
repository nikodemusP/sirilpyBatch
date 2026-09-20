import shutil
from sirilpy import LogColor # type: ignore
from sirilpyBatch import BatchPlugin, BatchPluginRegistry 


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
        self.cmd("cd","lights")
        self.cmd("convert","light","-out=../process")
        self.cmd("cd","../process")

        # ── 2) Calibrate the images ─────────────────────────────
        args = ["calibrate","light","-bias=../masters/bias_master","-dark=../masters/dark_master","-flat=../masters/flat_master"]
        if self.get_value("cfa"):
            args.append("-cfa ")
        if self.get_value("equalize_cfa"):
            args.append("-equalize_cfa")
        if self.get_value("debayer"):
            args.append("-debayer")
        self.context.siril.log(f"[INFO] calibrate", LogColor.GREEN)
        self.cmd(*args)        

        # ── 2) register ─────────────────────────────
        self.cmd("register","pp_light")
        # ── 3) stack the images ─────────────────────────────
        self.cmd("stack",
                 "r_pp_light",
                 "rej","3","3",
                 "-norm=addscale",
                 "-output_norm",
                 "-rgb_equal",
                 f"-out={self.result_name}"
                )

    def load(self):
        wd = self.get_siril_wd()
        self.cmd("load", f"{wd}/process/{self.result_name}")
