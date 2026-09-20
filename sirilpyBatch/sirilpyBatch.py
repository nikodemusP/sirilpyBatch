"""
sirilpyBatch - a Siril PyQt6 batch-processing front end.

Lets the user drag-and-drop plugins from a sidebar list into an ordered
batch, configure each one through its own widget box, reorder/remove them,
and run the batch against a running Siril instance. Batch composition and
per-plugin settings are persisted to YAML so a project can be reopened later.

Key building blocks:
    BatchConfig          - reads/writes the YAML config & presets files.
    BatchContext         - shared (siril, config) handle passed to plugins.
    PluginItem           - declarative description of one config widget.
    PluginConfigBox      - renders a plugin's PluginItem list + Load/Process buttons.
    BatchPlugin          - base class plugin authors subclass.
    BatchPluginRegistry  - collects plugins registered via @register(...).
    PluginContainer      - the drop target holding the ordered, active plugins.
    PluginList           - the draggable sidebar list of available plugins.
    Batch                - the main window tying everything together.
"""

import importlib.util
import os
import pathlib
import sys

import sirilpy as s # type: ignore
from sirilpy import LogColor # type: ignore

from PyQt6.QtWidgets import (
    QApplication,
)

from .Core.BatchProcessor import Batch

def load_plugins(plugin_dir: str) -> None:
    """
    Import every ``.py`` module in the plugins package (skipping files
    starting with "_", e.g. ``__init__.py``).

    Importing is enough to register a plugin: each module's
    ``@BatchPluginRegistry.register(...)``-decorated class runs its
    decorator as a side effect of the import, populating
    ``BatchPluginRegistry._entries``.
    """
    plugin_path = pathlib.Path(plugin_dir)
    print(f"{plugin_path.absolute()}")
    for file in plugin_path.glob("*.py"):
        if file.stem.startswith("_"):
            continue  # e.g. skip __init__.py
        print(f"load {file.name}")
        try:
            spec = importlib.util.spec_from_file_location(file.stem, file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as error:  # e.g. a malformed YAML item definition
            print(f"Skipping plugin {file.name}: {error}")


def execute(argv):
    """Application entry point: load plugins, build the Qt app, and run the main window."""
    try:
        plugin = os.path.dirname(os.path.realpath(__file__)) + "/Plugins"
        load_plugins(plugin)

        app = QApplication(argv)
        batch = Batch()

        # Only show window if initialization was successful
        if batch.initialization_successful:
            batch.show()
            sys.exit(app.exec())
        else:
            # User canceled during initialization - exit gracefully
            sys.exit(0)
    except Exception as e:
        print(f"Error initializing application: {str(e)}")
        sys.exit(1)