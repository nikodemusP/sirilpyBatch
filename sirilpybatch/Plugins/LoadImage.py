# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Nikolas Pommerening
# Contact: nikodemus.p@gmx.at
#
import os

from sirilpy import LogColor  # type: ignore
from sirilpybatch import BatchPlugin, BatchPluginRegistry


PLUGIN_CONFIG = """
Plugin:
    Key: load_image
    Title: Load Image
Box:
    Columns: 6
Items:
    - File:
        Key: image_file
        Label: Image
        DialogTitle: Select image to load
        NameFilter: "Image files (*.fit *.fits *.fts *.xisf *.tif *.tiff *.png *.jpg *.jpeg *.bmp);;All files (*)"
        colspan: 6
        SaveValue: False
"""


@BatchPluginRegistry.register(PLUGIN_CONFIG)
class LoadImagePlugin(BatchPlugin):

    def load(self):
        image_file = str(self.get_value("image_file") or "").strip()
        if not image_file:
            raise ValueError("Select an image file to load")
        if not os.path.isfile(image_file):
            raise FileNotFoundError(f"Image file does not exist: {image_file}")

        self.context.siril.log(f"Loading image: {image_file}", LogColor.GREEN)
        self.cmd("load", image_file).run()
