# SPDX-License-Identifier: GPL-3.0-or-later
from sirilpybatch import BatchPlugin, BatchPluginRegistry


Plugin_Config = """
Plugin:
    Key: green_noise
    Title: Green Noise
    targetName: ["gn"]
Box:
    Columns: 5
Items:
    - CheckBox:
        Key: nopreserve
        Label: Do not preserve lightness
        Default: False
    - ComboBox:
        Key: type
        Label: Type
        Values: [0, 1, 2, 3]
        Default: 0
        Tooltip: "0: average neutral; 1: maximum neutral; 2: maximum mask; 3: additive mask"
    - Separator
    - FloatItem:
        Key: amount
        Label: Amount
        Default: 1.0
        Minimum: 0.0
        Maximum: 1.0
        Step: 0.05
    - CheckBox:
        Key: mask
        Label: Apply to mask
        Default: False
"""

@BatchPluginRegistry.register(Plugin_Config)
class GreenNoisePlugin(BatchPlugin):

    def process(self):
        self.cmd("cd","./process").run()
        green_type = self.get_value("type")
        cmd = self.cmd("rmgreen")
        cmd.add_opt("-nopreserve", self.get_value("nopreserve"))
        cmd.add_arg("{}", green_type)
        if green_type in (2, 3):
            cmd.add_arg("{}", self.get_value("amount"))
        cmd.add_opt("-mask", self.get_value("mask"))
        cmd.run()
        self.save()

    def getResultFile(self):
        return 0