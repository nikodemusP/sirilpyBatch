# 1. Package Metadata
__version__ = "0.1.2"
__app_name__ = "sirilpybatch"

# Standard capitals for global constants within your code
VERSION = __version__
APP_NAME = __app_name__

# 2. Expose your package functions
from .sirilpybatch import execute

from .sirilpybatch import execute
from .Core.PluginItem import PluginItem, registerItem
from .Core.BatchPlugin import BatchPlugin, BatchCmd
from .Core.Registry import BatchPluginRegistry 
from .Core.BatchContext import BatchContext
from .Core.Utils import scanDirectory, FrameInfo

# (Optional) Control what gets imported with "from sirilpybatch import *"
__all__ = ["execute", "BatchPlugin", "BatchPluginRegistry", "BatchCmd", "BatchContext", "scanDirectory", "FrameInfo", "PluginItem", "registerItem", "VERSION", "APP_NAME"]

