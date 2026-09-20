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
      * ``sirilpyBatch.yaml``    - user-wide presets, stored in Siril's user data
                                   directory so they survive across projects.
    """

    def __init__(self, siril):
        self.siril = siril
        #config_dir = Path(siril.get_siril_userdatadir())
        #config_dir.mkdir(parents=True, exist_ok=True)
        main = sys.modules["__main__"]
        main_dir = Path(main.__file__).resolve().parent
        cfg_dir = Path(__file__).resolve().parent.parent / "cfg"
        self.presets_file = main_dir / "sirilpyBatch.yaml"
        self.global_config_file = cfg_dir / "sirilpyConfig.yaml"
        self._readConfig()

    def get_value(self, key: str, default: Any = None):
        """Resolve values such as telescope.focalLen."""
        value: Any = self.config
        for part in key.split("."):
            if not isinstance(value, dict):
                return default
            value = value.get(part)
            if value is None:
                return default
        return value

    def _readConfig(self):
        global_config = self._readGlobalConfig() or {}
        preset_config = self._readPresetConfig() or {}
        self.config   = {
            **global_config,
            **preset_config,            
        }

    def _readGlobalConfig(self):
        """Load the shared telescope/sensor configuration."""
        if not self.global_config_file.exists():
            self.siril.log(
                f"Global config not found: {self.global_config_file}",
                LogColor.RED,
            )
            return {}

        try:
            with open(self.global_config_file, "r", encoding="utf-8") as file:
                config = yaml.safe_load(file)

            self.siril.log(
                "Global configuration loaded successfully.",
                LogColor.GREEN,
            )
            return config if isinstance(config, dict) else {}

        except Exception as error:
            self.siril.log(
                f"Error reading global config: {error}",
                LogColor.RED,
            )
            return {}

    def _readPresetConfig(self):
        """Load the user-wide presets file, or None if it doesn't exist yet / fails to parse."""
        self.siril.log(f"read preset config", LogColor.GREEN)
        if not self.presets_file.exists():
            self.siril.log("Presets file not found: sirilpyBatch.yaml", LogColor.RED)
            return None
        try:
            with open(self.presets_file, "r") as f:
                presets = yaml.safe_load(f)
                self.siril.log("Presets loaded successfully.", LogColor.GREEN)
                return presets
        except Exception as e:
            self.siril.log(f"Error reading presets file: {str(e)}", LogColor.RED)
            return None

    def storePresets(self, config):
        """Persist the user-wide presets dict to ``sirilpyBatch.yaml``."""
        try:
            # Merge into what is already on disk so keys we weren't handed
            # (anything besides "Batches"/"telescope") are not wiped out.
            merged = self._readPresetConfig() if self.presets_file.exists() else None
            merged = dict(merged) if isinstance(merged, dict) else {}
            merged.update(config)
            merged["telescope"] = self.config.get("telescope", {})
            with open(self.presets_file, "w") as f:
                yaml.safe_dump(merged, f)
            # Re-read only after the file is closed/flushed.
            self._readConfig()
            self.siril.log("Configuration saved successfully.", LogColor.GREEN)
        except Exception as e:
            self.siril.log(f"Error saving configuration file: {str(e)}", LogColor.RED)

    def telescope_list(self):
        return self.config.get("telescopes", [])

    def selected_telescope_name(self):
        return self.config.get("telescope", {}).get("name", "")

    def set_selected_telescope(self, name):
        selected_telescope = next(
            (
                telescope
                for telescope in self.telescope_list()
                if telescope.get("name") == name
            ),
            None,
        )

        if selected_telescope is not None:
            self.config["telescope"] = deepcopy(selected_telescope)