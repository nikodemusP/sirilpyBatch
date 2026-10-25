# SPDX-License-Identifier: GPL-3.0-or-later
from sirilpy import LogColor  # type: ignore
from sirilpybatch import BatchPlugin, BatchPluginRegistry


PLUGIN_CONFIG = """
Plugin:
    Key: graxpert_denoise
    Title: GraXpert Denoise
    targetName: ["graxpert_denoise"]
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

@BatchPluginRegistry.register(PLUGIN_CONFIG)
class GraXpertDenoisePlugin(BatchPlugin):

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
        self.save(0)

    def get_result_file(self):
        return 0
