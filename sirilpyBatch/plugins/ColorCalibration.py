import shutil
from pathlib import Path
from dataclasses import dataclass
from sirilpyBatch.sirilpyBatch import BatchPlugin, BatchPluginRegistry, CheckboxItem, ComboBoxItem, FloatItem, PluginItem, SeparatorItem
from sirilpy import LogColor

calibration_items = [
    CheckboxItem(
        key="plade",          
        label="Pladesolve",
        colspan=2,
        default=True),
    SeparatorItem(),
    CheckboxItem(
        key="pcc", 
        label="Photometric Color Calibration", 
        colspan=2,
        default=False),
    CheckboxItem(
        key="spcc",      
        label="Spectrophotometric Color Calibration",      
        colspan=2,
        default=False),
    SeparatorItem(),
    ComboBoxItem(
        key="catalogue",
        label="Catalogue",
        values=["apass", "localgaia", "gaia","nomad"],
        default="nomad",
    ),
    FloatItem(
        key="bgtol_lower",    
        label="Tolerance Low",    
        colspan=2,
        default=-2.8),
    FloatItem(
        key="bgtol_upper",   
        label="High",   
        colspan=2,
        default=2.0),
    SeparatorItem(),
]

@BatchPluginRegistry.register(key="color_calibration", title="Color Calibration", items=calibration_items, columns=6)
class CalibratePlugin(BatchPlugin):

    result_name = "calibration"

    def process(self):
        # ── 1) Convert Lights ─────────────────────────────
        self.context.siril.log(f"[INFO] plade solve", LogColor.GREEN)
        low = float(self.get_value("bgtol_lower"))
        high = float(self.get_value("bgtol_upper"))
        catalog = self.get_value("catalogue")
        self.cmd("cd","process")
        if self.get_value("plade"):
            self.cmd("platesolve")
        if self.get_value("pcc"):
            args = ["pcc",
                    f"-bgtol={low:.1f},{high:.1f}",
                    f"-catalog={catalog}",
                   ]
            self.cmd(args)
        if self.get_value("spcc"):
            args = ["spcc",
                    f"-bgtol={low:.1f},{high:.1f}",
                    f"-catalog={catalog}",
                   ]
            self.cmd(args)
        self.cmd("save","result_calibration")

    def load(self):
        wd = self.get_siril_wd()
        self.cmd("load", f"{wd}/process/{self.result_name}")
