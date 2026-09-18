import shutil
from pathlib import Path
from dataclasses import dataclass
from sirilpyBatch.sirilpyBatch import BatchPlugin, BatchPluginRegistry, CheckboxItem, IntItem, PluginItem, SeparatorItem
from sirilpy import LogColor

calibrate_items = [
    CheckboxItem(
        key="cfa",          
        label="CFA format",
        colspan=2,
        default=False),
    CheckboxItem(
        key="equalize_cfa", 
        label="equalize CFA", 
        colspan=2,
        default=False),
    CheckboxItem(
        key="debayer",      
        label="Debayer",      
        colspan=2,
        default=False),
    SeparatorItem(
        key="sep1"),
    IntItem(
        key="sigma_low",    
        label="Sigma Low",    
        colspan=2,
        default=3),
    IntItem(
        key="sigma_high",   
        label="Sigma High",   
        colspan=2,
        default=3),
]

@BatchPluginRegistry.register(key="calibrate", title="Calibrate", items=calibrate_items, columns=6)
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
