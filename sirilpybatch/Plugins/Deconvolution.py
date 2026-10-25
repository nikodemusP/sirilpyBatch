# SPDX-License-Identifier: GPL-3.0-or-later
import os

from sirilpybatch import BatchPlugin, BatchPluginRegistry


PLUGIN_CONFIG = """
Plugin:
    Key: deconvolution
    Title: Deconvolution
    targetName: ["decon"]
Box:
    Columns: 4
Items:
    - ComboBox:
        Key: algorithm
        Label: Algorithm
        Values: ["Richardson-Lucy", "Split Bregman", "Wiener"]
        Default: "Richardson-Lucy"
    - IntItem:
        Key: iters
        Label: Iterations
        Default: 10
        Minimum: 1
        Maximum: 1000
"""


@BatchPluginRegistry.register(PLUGIN_CONFIG)
class DeconvolutionPlugin(BatchPlugin):

    psf_path = "process/psf.fits"

    def process(self):
        work_dir = self.get_siril_wd()
        process_dir = os.path.join(work_dir, "process")
        os.makedirs(process_dir, exist_ok=True)

        self.cmd("makepsf", "stars", f"-savepsf={self.psf_path}").run()

        algorithm = self.get_value("algorithm")
        command = {
            "Richardson-Lucy": "rl",
            "Split Bregman": "sb",
            "Wiener": "wiener",
        }[algorithm]
        cmd = self.cmd(command, f"-loadpsf={self.psf_path}")
        if command in ("rl", "sb"):
            cmd.add_arg("-iters={}", self.get_value("iters"))
        cmd.run()
        self.save(0)

    def get_result_file(self):
        return 0
