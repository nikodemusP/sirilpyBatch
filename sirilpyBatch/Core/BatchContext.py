# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Nikolas Pommerening
# Contact: nikodemus.p@gmx.at
#
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

