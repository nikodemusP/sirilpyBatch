import shutil
from pathlib import Path
from dataclasses import dataclass
from sirilpyBatch.sirilpyBatch import BatchPlugin, BatchPluginRegistry, CheckboxItem, ComboBoxItem, FloatItem, IntItem, PluginItem, SeparatorItem
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
        values=["none","apass", "localgaia", "gaia","nomad"],
        default="gaia",
    ),
    IntItem(
        key="bgtol_lower",    
        label="Tolerance Low",    
        colspan=1,
        default=0),
    IntItem(
        key="bgtol_upper",   
        label="High",   
        colspan=1,
        default=2),
    SeparatorItem(),
]

@BatchPluginRegistry.register(key="color_calibration", title="Color Calibration", items=calibration_items, columns=6)
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
        low = int(self.get_value("bgtol_lower"))
        high = int(self.get_value("bgtol_upper"))
        catalog = self.get_value("catalogue")

        if catalog != "none":
            args.append(f"-catalog={catalog}")
        else:
            args.append(f"-bgtol={low},{high}")
        self.cmd(*args)

    def spcc(self):
        args = ["spcc"]
        low = int(self.get_value("bgtol_lower"))
        high = int(self.get_value("bgtol_upper"))
        sensor = self.get_config("telescope.sensor","")

        self.cmd("spcc",
                 f"\"-oscsensor={sensor}\"",
                 f"\"-oscfilter=No filter\"",
                 f"-bgtol={low},{high}")

    def load(self):
        wd = self.get_siril_wd()
        self.cmd("load", f"{wd}/process/{self.result_name}")
