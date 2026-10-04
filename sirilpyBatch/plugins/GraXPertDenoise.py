# SPDX-License-Identifier: GPL-3.0-or-later
from sirilpy import LogColor  # type: ignore
from sirilpyBatch import BatchPlugin, BatchPluginRegistry


Plugin_Config = """
Plugin:
    Key: graxpert_denoise
    Title: GraXpert Denoise
Box:
    Columns: 4
Items:
    - ComboBox:
        Key: model
        Label: Model version
        Values: ["3.0.2","3.0.1"]
        Default: "3.0.2"
    - CheckBox:
        Key: gpu
        Label: use GPU
        Default: True
    - Separator
    - FloatItem:
        Key: strength
        Label: Strength
        Default: 0.5
        Step: 0.1
"""

@BatchPluginRegistry.register(Plugin_Config)
class GraXpertDenoisePlugin(BatchPlugin):

    result_name = "denoise"

    def save(self):
        wd = self.get_siril_wd()
        self.cmd("save",f"{wd}/process/{self.result_name}").run()

    def process(self):
        self.cmd("cd","./process").run()
        # Exchange the file, the GraXpert operates on the original file
        self.save()
        self.load()
        cmd = self.cmd("pyscript", "GraXpert-AI.py", "-denoise")

        model = self.get_value("model")
        if model:
            cmd.add_arg("-model={}", model)

        cmd.add_opt("-gpu", self.get_value("gpu"))
        cmd.add_opt("-nogpu", not self.get_value("gpu"))
        cmd.add_arg("-strength={}", self.get_value("strength"))

        cmd.run()

    def load(self):
        wd = self.get_siril_wd()
        self.cmd("load", f"{wd}/process/{self.result_name}").run()