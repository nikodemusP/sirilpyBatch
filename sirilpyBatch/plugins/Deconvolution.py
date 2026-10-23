# SPDX-License-Identifier: GPL-3.0-or-later
import os

from sirilpyBatch import BatchPlugin, BatchPluginRegistry


Plugin_Config = """
Plugin:
    Key: deconvolution
    Title: Deconvolution
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


@BatchPluginRegistry.register(Plugin_Config)
class DeconvolutionPlugin(BatchPlugin):

    result_name = "deconvolution"
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
        self.cmd("save", f"process/{self.result_name}").run()

    def load(self):
        wd = self.get_siril_wd()
        self.cmd("load", f"{wd}/process/{self.result_name}").run()
