# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Nikolas Pommerening
# Contact: nikodemus.p@gmx.at
#
from dataclasses import dataclass
from typing import Any, Type

from .BatchConfig import BatchConfig
from .BatchPlugin import BatchPlugin
from .PluginItem import PluginItem

# ------------------------------------------------------------------------------------------
# This module exists to break an import cycle:
#
#   Registry        needs BatchPluginEntry (to build entries in @register)
#   BatchProcessor  needs Registry         (to list/lookup plugins)
#
# BatchPluginEntry used to live in BatchProcessor, so the two modules imported each other.
# It now lives here and depends only on BatchPlugin / BatchConfig / PluginItem, none of
# which import Registry or BatchProcessor.
# ------------------------------------------------------------------------------------------


@dataclass
class BatchPluginEntry:
    """
    Static metadata describing one registered plugin type, as produced by
    ``@BatchPluginRegistry.register(...)``. This is the "blueprint"; call
    ``instantiate()`` to get a live ``BatchPlugin`` bound to a context.
    """

    plugin_cls: Type[BatchPlugin]
    key: str
    title: str
    items: list[PluginItem]
    columns: int = 5
    enabled: bool = True

    def instantiate(
        self,
        siril: Any,
        config: BatchConfig,
        plugin_config: dict | None = None,
    ) -> BatchPlugin:
        """Create and set up a fresh plugin instance from this entry."""
        instance = self.plugin_cls(siril, config)
        instance.set_up(
            key=self.key,
            title=self.title,
            items=self.items,
            columns=self.columns,
            plugin_config=plugin_config,
        )
        return instance