from sirilpy import LogColor # type: ignore
from sirilpyBatch import BatchPlugin, BatchPluginRegistry 


Plugin_Config = """
Plugin:
    Key: template
    Title: Template Plugin
Box:
    Columns: 6
Items:
    - CheckBox:
        Key: cfa
        Label: CFA format
        Default: False
    - CheckBox:
        Key: equalize_cfa
        Label: equalize CFA
        Default: False
    - CheckBox:
        Key: debayer
        Label: Debayer
        Default: False
    - Separator
    - IntRange:
        Key: sigma
        Label: Sigma
        Default: 3,3
"""

@BatchPluginRegistry.register(Plugin_Config)
class CalibratePlugin(BatchPlugin):

    result_name = "template"

    def process(self):
        """ What ever has to be processing """

    def load(self):
        """ If I can reload a processed image """
        wd = self.get_siril_wd()
        self.cmd("load", f"{wd}/process/{self.result_name}")