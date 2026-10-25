# SPDX-License-Identifier: GPL-3.0-or-later
import os

from sirilpybatch import BatchPlugin, BatchPluginRegistry


Plugin_Config = """
Plugin:
    Key: crop
    Title: Crop
    targetName: ["crop"]
Box:
    Columns: 1
Items: []
"""


@BatchPluginRegistry.register(Plugin_Config)
class CropPlugin(BatchPlugin):

    def process(self):
        if not self.original_image:
            raise ValueError("Load an image in Siril before cropping")

        if not self.confirm(
            "Crop selection",
            "Mark the area to keep in Siril, then click OK to crop.",
        ):
            return False

        self.cmd("boxselect").run()
        selection = self.siril().get_siril_selection()
        if selection is None:
            raise ValueError("Mark a crop area in Siril before clicking OK")

        x, y, width, height = selection
        if width <= 0 or height <= 0:
            raise ValueError(f"Invalid crop selection: {selection}")

        self.undo()

        os.makedirs(os.path.join(self.get_siril_wd(), "process"), exist_ok=True)
        self.cmd("cd", "./process").run()
        self.cmd(
            "crop",
            str(x),
            str(y),
            str(width),
            str(height),
        ).run()
        self.cmd("save", self.getOutFile(0)).run()

    def getResultFile(self):
        return 0
