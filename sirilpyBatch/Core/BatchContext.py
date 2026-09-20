# ------------------------------------------------------------------------------------------
from dataclasses import dataclass
from typing import Any

from .BatchConfig import BatchConfig

@dataclass
class BatchContext:
    """
    Shared, read-only-ish handle passed to every plugin instance.

    Bundles the live Siril connection (``siril``) together with the project's
    persisted configuration dict (``config``), so plugins never need to know
    where either of those come from.
    """

    siril: Any
    config: BatchConfig
    plugin_config: dict

