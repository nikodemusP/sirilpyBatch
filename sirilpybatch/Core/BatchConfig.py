# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Nikolas Pommerening
# Contact: nikodemus.p@gmx.at
#
from copy import deepcopy
from pathlib import Path
import sys
from typing import Any
import yaml
import sirilpy as s # type: ignore
from sirilpy import LogColor # type: ignore

# ------------------------------------------------------------------------------------------
class BatchConfig:
    """
    Reads and writes the plugin's on-disk configuration.

    Two separate files are involved:
      * ``sirilpybatch.yaml``    - user-wide presets, stored in Siril's user data
                                   directory so they survive across projects.
    """

    def __init__(self, siril):
        self.siril = siril
        # Read the global config 
        cfg_dir = Path(__file__).resolve().parent.parent / "cfg"
        self.global_config_file = cfg_dir / "sirilpyConfig.yaml"
        self.config = self._read_file(self.global_config_file) or {}
        self.siril.log(
                "Global configuration loaded successfully.",
                LogColor.GREEN,
            )

        # Read the user-wide presets from the same directory as the main script.
        main = sys.modules["__main__"]
        main_dir = Path(main.__file__).resolve().parent
        self.config_file = main_dir / "sirilpybatch.yaml"
        self.presets = self._read_file(self.config_file) or {}
        self.siril.log(
                "User presets loaded successfully.",
                LogColor.GREEN,
            )

    def cfg(self, key: str, default: Any = None):
        """Resolve values using dotted paths into the merged configuration."""
        value: Any = self.config
        for part in key.split("."):
            if not isinstance(value, dict):
                return default
            value = value.get(part)
            if value is None:
                return default
        return value
    
    def get_value(self, key: str, default: Any = None):
        """Resolve values using dotted paths into the merged configuration."""
        value: Any = self.presets
        for part in key.split("."):
            if not isinstance(value, dict):
                return default
            value = value.get(part)
            if value is None:
                return default
        return value

    def set_value(self, key: str, value: Any):
        """Set a value in the presets using a dotted path, creating nested mappings."""
        parts = key.split(".")
        if not key or any(not part for part in parts):
            raise ValueError("Configuration key must contain non-empty path components")

        target = self.presets
        for part in parts[:-1]:
            current = target.get(part)
            if current is None:
                current = {}
                target[part] = current
            if not isinstance(current, dict):
                raise TypeError(f"Configuration path '{part}' is not a mapping")
            target = current
        target[parts[-1]] = value

    def _read_file(self, file_path: Path):
        """Load the user-wide presets."""
        if not file_path.exists():
            return {}
        try:
            with open(file_path, "r", encoding="utf-8") as file:
                config = yaml.safe_load(file)
            return config if isinstance(config, dict) else {}
        except Exception as error:
            self.siril.log(
                f"Error reading file {file_path}: {error}",
                LogColor.RED,
            )
            return {}

    def store_presets(self):
        """Persist the user-wide presets dict to ``sirilpybatch.yaml``."""
        try:
            with open(self.config_file, "w") as f:
                yaml.safe_dump(self.presets, f)
            self.siril.log("Configuration saved successfully.", LogColor.GREEN)
        except Exception as e:
            self.siril.log(f"Error saving configuration file: {str(e)}", LogColor.RED)
