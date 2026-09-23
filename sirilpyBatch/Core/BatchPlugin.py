# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Nikolas Pommerening
# Contact: nikodemus.p@gmx.at
#
from typing import Any

from sirilpy import LogColor # type: ignore

from .PluginConfigBox import PluginConfigBox
from .PluginItem import PluginItem
from .BatchContext import BatchContext 
from .BatchConfig import BatchConfig 

class BatchCmd:
    def __init__(self, siril):
        self.siril = siril
        self.args = []

    def append(self, *args):
        if args:
            self.args.extend(args)
        return self

    def add_arg(self, template, *values):
        """
        Format `template` with one or more values and append it as one arg.

        Supports:
        add_arg("-bias={}", value)              # single value
        add_arg("-catalog={},{}", low, high)     # multiple positional values
        add_arg("-catalog={},{}", (low, high))   # single tuple/list, unpacked
        """
        if not values:
            return self

        # unwrap a single tuple/list argument into multiple values
        if len(values) == 1 and isinstance(values[0], (tuple, list)):
            values = tuple(values[0])

        if any(v is None for v in values):
            return self

        self.args.append(f'"{template.format(*values)}"')
        return self

    def add_opt(self, option, condition):
        if condition:
            self.args.append(option)
        return self

    def run(self):
        self.siril.log(f"[CMD] {' '.join(self.args)}", LogColor.GREEN)
        return self.siril.cmd(*self.args)

    def __iter__(self):
        return iter(self.args)

    
class BatchPlugin:
    """
    Abstract base class for all batch plugins.

    Subclasses declare their UI via ``set_Up`` (called by the registry/entry)
    and implement whichever of ``process()`` / ``load()`` they need:
      * ``process()`` runs the plugin's main batch action.
      * ``load()`` runs a lighter "preview/load only" action.
    Whether the "Process" and/or "Load" buttons are shown is decided
    automatically in ``create_plugin_box`` based on which of these methods
    a subclass actually overrides.
    """

    def __init__(self, siril: Any, config: BatchConfig ):
        self.context = BatchContext(
            siril=siril,
            config=config,
            work_dir=siril.get_siril_wd(),
            plugin_config={},
        )

    def set_up(self, key: str, title: str, items: list[PluginItem], columns: int = 5, plugin_config: dict | None = None):
        """Called once after construction to bind this instance to its registry entry."""
        self.plugin_items = items
        self.key_name = key
        self.title = title
        self.columns = columns
        self.context.plugin_config = plugin_config if plugin_config is not None else {}
        self.context.siril.log(f"setup plugin: {self.title}", LogColor.GREEN)

    def create_plugin_box(self):
        """
        Build the ``PluginConfigBox`` widget for this plugin.

        Detects whether the subclass overrides ``process``/``load`` (versus
        inheriting the no-op default) to decide which action buttons to show,
        and wires those buttons to ``_on_process``/``_on_load``.
        """
        has_process = type(self).process is not BatchPlugin.process
        has_load = type(self).load is not BatchPlugin.load

        self.box = PluginConfigBox(
            self.title,
            self.plugin_items,
            has_load=has_load,
            has_process=has_process,
            columns=self.columns,
            context=self.context
        )

        if has_process:
            self.box.processRequested.connect(self._on_process)
        if has_load:
            self.box.loadRequested.connect(self._on_load)

        return self.box

    def get_key_name(self):
        """Returns the internal registry key of the plugin."""
        return self.key_name

    def get_plugin_name(self):
        """Returns the display title of the plugin."""
        return self.title

    def cmd(self, *args) -> BatchCmd:
        return BatchCmd(self.context.siril).append(*args)
    
    def _on_process(self):
        """
        Handler for the "Process" button: runs ``process()``, always returns
        to the original working directory afterwards, then runs ``load()``
        (if defined) so the result is immediately reflected in the UI.
        """
        self.cmd("cd", self.context.work_dir).run()
        has_load = type(self).load is not BatchPlugin.load
        try:
            self.process()
            if has_load:
                self.load()
        except Exception as e:
            self.context.siril.log(f"Error during execution: {e}", LogColor.RED)
        self.cmd("cd", self.context.work_dir).run()

    def _on_load(self):
        """Handler for the "Load" button."""
        self.load()

    def process(self):
        """Override to implement the plugin's main batch action. No-op by default."""
        pass

    def load(self):
        """Override to implement a lightweight preview/load action. No-op by default."""
        pass

    def siril(self):
        """Convenience accessor for the shared Siril interface."""
        return self.context.siril

    def get_siril_wd(self):
        """Convenience accessor for Siril's current working directory."""
        return self.context.work_dir

    def get_config(self, key: str, default):
        return self.context.config.get_value(key,default)
    
    def get_value(self, key: str):
        """Read the current value of one of this plugin's config widgets."""
        return self.box.get_value(key)

    @property
    def config(self):
        """The plugin's persisted settings dict (as loaded in ``set_up``)."""
        return self.context.plugin_config

    @config.setter
    def config(self, value):
        self.context.plugin_config = value