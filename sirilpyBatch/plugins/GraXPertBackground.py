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
    - Text:
        Key: model
        Label: Model version
        Default: ""
    - CheckBox:
        Key: gpu
        Label: use GPU
        Default: True
    - CheckBox:
        Key: keep_bg
        Label: keep background
        Default: False
    - Separator
    - FloatRange:
        Key: strength
        Label: Strength
        Default: [0,0.1]
    - ComboBox:
        Key: correction
        Label: Correction
        Options: [subtraction, division]
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
        cmd.add_opt("-keep-bg", self.get_value("keep_bg"))
        cmd.add_arg("-smoothing={}", self.get_value("smoothing"))
        cmd.add_arg("-correction={}", self.get_value("correction"))

        cmd.run()