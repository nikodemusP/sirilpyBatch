# SPDX-License-Identifier: GPL-3.0-or-later
import os

from sirilpybatch import BatchPlugin, BatchPluginRegistry


PLUGIN_CONFIG = """
Plugin:
    Key: crop
    Title: Crop
    targetName: ["crop"]
Box:
    Columns: 7
Items:
    - Radio:
        Key: crop_margin
        Label: Crop margin
        Values: ["0.0%", "2.5%", "5.0%", "7.5%", "10.0%","box-select"]
        Default: "5.0%"
"""


@BatchPluginRegistry.register(PLUGIN_CONFIG)
class CropPlugin(BatchPlugin):

    def get_crop_margin(self):
        margin_str = self.get_value("crop_margin")
        if margin_str.endswith("%"):
            try:
                return float(margin_str[:-1]) / 100.0
            except ValueError:
                raise ValueError(f"Invalid crop margin: {margin_str}")
        return -1.0  # Default to -1.0 if no valid margin is found
    
    def process(self):
        if not self.original_image:
            raise ValueError("Load an image in Siril before cropping")

        margin = self.get_crop_margin()
        if margin >= 0.0:
            # Calculate crop dimensions based on the margin
            shape = self.siril().get_image_shape()
            if shape is None:
                raise ValueError("Could not get the loaded image shape from Siril")

            _channels, height, width = shape
            x = int(width * margin)
            y = int(height * margin)
            width = int(width * (1 - 2 * margin))
            height = int(height * (1 - 2 * margin))
        else:
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

        self.cmd(
            "crop",
            f"{x}",
            f"{y}",
            f"{width}",
            f"{height}",
        ).run()
        self.cmd("save", self.get_out_file(0)).run()

    def get_result_file(self):
        return 0
