# 1. Package Metadata
__version__ = "0.1.0"
__app_name__ = "sirilpyBatch"

# Standard capitals for global constants within your code
VERSION = __version__
APP_NAME = __app_name__

# 2. Expose your package functions
from .sirilpyBatch import execute

from .sirilpyBatch import execute
from .Core.BatchPlugin import BatchPlugin, BatchCmd
from .Core.Registry import BatchPluginRegistry 

# (Optional) Control what gets imported with "from sirilpyBatch import *"
__all__ = ["execute", "BatchPlugin", "BatchPluginRegistry", "BatchCmd", "VERSION", "APP_NAME"]

