# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Nikolas Pommerening
# Contact: nikodemus.p@gmx.at
#
import os
from typing import Any, Callable

from sirilpy import LogColor # type: ignore
from PyQt6.QtWidgets import QMessageBox

from .BatchCmd import BatchCmd, set_batch_command_output
from .PluginBox import PluginBox
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
      * Returning ``False`` from ``process()`` skips the automatic post-process load.
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
        self.original_image: str | None = None

    def set_up(
        self,
        key: str,
        title: str,
        items: list[PluginItem],
        columns: int = 5,
        plugin_config: dict | None = None,
        target_names: list[str] | None = None,
    ):
        """Called once after construction to bind this instance to its registry entry."""
        self.plugin_items = items
        self.key_name = key
        self.title = title
        self.columns = columns
        self.target_names = list(target_names or [])
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
        has_load = type(self).get_result_file is not BatchPlugin.get_result_file

        self._resolve_callbacks()

        self.box = PluginBox(
            self.title,
            self.plugin_items,
            has_load=has_load,
            has_process=has_process,
            columns=self.columns,
            context=self.context
        )

        if has_process:
            self.box.process_requested.connect(self._on_process)
        if has_load:
            self.box.load_requested.connect(self._on_load)

        return self.box

    def _resolve_callbacks(self):
        """Bind each item's ``on_change`` callback to a method on this plugin."""
        for item in self.plugin_items:
            name = getattr(item, "on_change", None)
            if not name or item.callback is not None:
                continue
            method = getattr(self, str(name), None)
            if callable(method):
                item.callback = method  # called as method(value, key)
            else:
                self.context.siril.log(
                    f"{self.title}: on_change '{name}' for '{item.key}' is not a method of "
                    f"{type(self).__name__}",
                    LogColor.RED,
                )

    def load(self):
        idx = self.get_result_file()
        file_name = self.get_out_file(idx)
        self.context.siril.log(f"Loading result file: {file_name}", LogColor.GREEN)
        cmd = self.cmd("load", file_name)
        cmd.run()

    def save(self, idx: int = 0):
        file_name = self.get_out_file(idx)
        self.cmd("save", file_name).run()

    def get_key_name(self):
        """Returns the internal registry key of the plugin."""
        return self.key_name

    def get_plugin_name(self):
        """Returns the display title of the plugin."""
        return self.title

    def get_out_file(self, idx: int) -> str:
        """Return the result path for the target name at ``idx``."""
        if not isinstance(idx, int) or isinstance(idx, bool):
            raise TypeError("target name index must be an integer")
        if idx < 0 or idx >= len(self.target_names):
            raise IndexError(
                f"target name index {idx} out of range for {len(self.target_names)} target name(s)"
            )

        project_name = str(self.get_config("project_name", "") or "").strip()
        if not project_name:
            project_name = os.path.basename(os.path.normpath(self.get_siril_wd()))

        filename = f"{project_name}_{self.target_names[idx]}"
        return os.path.join(self.get_siril_wd(), "result", filename)

    def get_out_file_arg(self, idx: int) -> str:
        """Return the indexed result path formatted as a quoted Siril command argument."""
        path = self.get_out_file(idx).replace("\\", "/")
        return f'"{path}"'

    def cmd(self, *args) -> BatchCmd:
        return BatchCmd().append(*args)

    def confirm(self, title: str, message: str) -> bool:
        """Show a reusable OK/Cancel confirmation dialog for plugin actions."""
        answer = QMessageBox.question(
            getattr(self, "box", None),
            title,
            message,
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Ok

    def undo(self):
        """Reload the image captured when this plugin's process action began."""
        if not self.original_image:
            raise RuntimeError("No original image was captured for this process")
        self.cmd("load", self.original_image).run()

    def execute(self):
        """
        Handler for the "Process" button: runs ``process()``, always returns
        to the original working directory afterwards, then runs ``load()``
        (if defined) so the result is immediately reflected in the UI.
        """
        self.cmd("cd", self.context.work_dir).run()
        has_load = type(self).load is not BatchPlugin.load
        try:
            self.original_image = None
            if self.siril().is_image_loaded():
                original_image = self.siril().get_image_filename()
                if original_image:
                    if not os.path.isabs(original_image):
                        original_image = os.path.join(self.context.work_dir, original_image)
                    self.original_image = original_image
            process_result = self.process()
            if has_load and process_result is not False:
                self.load()
        except Exception as e:
            self.context.siril.log(f"Error during execution: {e}", LogColor.RED)
        #self.cmd("cd", self.context.work_dir).run()
    
    def _on_process(self):
        set_batch_command_output(self.context.siril.cmd)
        self.execute()

    def _on_load(self):
        """Handler for the "Load" button."""
        self.load()

    def process(self):
        """Override to implement the plugin's main batch action. No-op by default."""
        pass

    def get_result_file(self):
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