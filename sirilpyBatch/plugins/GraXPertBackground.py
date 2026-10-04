# SPDX-License-Identifier: GPL-3.0-or-later
from sirilpy import LogColor  # type: ignore
from sirilpyBatch import BatchPlugin, BatchPluginRegistry


Plugin_Config = """
Plugin:
    Key: graxpert_bge
    Title: GraXpert Background
Box:
    Columns: 4
Items:
    - ComboBox:
        Key: model
        Label: Model version
        Values: ["1.0.0","1.0.1"]
        Default: "1.0.1"
    - CheckBox:
        Key: gpu
        Label: use GPU
        Default: True
    - Separator
    - FloatItem:
        Key: smoothing
        Label: Smooting
        Default: 0.5
        Step: 0.1
    - ComboBox:
        Key: correction
        Label: Correction
        Values: ["subtraction", "division"]
        Default: subtraction
"""

@BatchPluginRegistry.register(Plugin_Config)
class GraXpertBackgroundPlugin(BatchPlugin):

    def process(self):
        cmd = self.cmd("pyscript", "GraXpert-AI.py", "-bge")

        model = self.get_value("model")
        if model:
            cmd.add_arg("-model={}", model)

        cmd.add_opt("-nogpu", not self.get_value("gpu"))
        cmd.add_opt("-gpu", self.get_value("gpu"))
        cmd.add_arg("-smoothing={}", self.get_value("smoothing"))
        cmd.add_arg("-correction={}", self.get_value("correction"))

        cmd.run()