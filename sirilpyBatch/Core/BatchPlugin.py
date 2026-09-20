# ------------------------------------------------------------------------------------------
from typing import Any

from sirilpy import LogColor # type: ignore

from .PluginConfigBox import PluginConfigBox
from .PluginItem import PluginItem
from .BatchContext import BatchContext 
from .BatchConfig import BatchConfig 

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

    def cmd(self, *args):
        """Run a single Siril command, logging it first."""
        self.context.siril.log(f"[CMD] {' '.join(args)}", LogColor.GREEN)
        self.context.siril.cmd(*args)

    def get_key_name(self):
        """Returns the internal registry key of the plugin."""
        return self.key_name

    def get_plugin_name(self):
        """Returns the display title of the plugin."""
        return self.title

    def _on_process(self):
        """
        Handler for the "Process" button: runs ``process()``, always returns
        to the original working directory afterwards, then runs ``load()``
        (if defined) so the result is immediately reflected in the UI.
        """
        workdir = self.get_siril_wd()
        has_load = type(self).load is not BatchPlugin.load
        try:
            self.process()
        except Exception as e:
            self.context.siril.log(f"Error during execution: {e}", LogColor.RED)
        self.cmd("cd", workdir)
        if has_load:
            self.load()

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
        return self.context.siril.get_siril_wd()

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