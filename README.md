# sirilpyBatch

A batch-processing front end for [Siril](https://siril.org). Build a processing pipeline by dragging plugins into an ordered list, configure each one in its own settings box, and run the whole chain against your running Siril session. Batches can be saved as named presets and reloaded later.

Every processing step is a small **plugin**: one Python file plus a short YAML block that describes its settings UI. Adding a new step to the batch means dropping a new file into `sirilpyBatch/Plugins/`. Nothing else has to be changed. [`_TemplatePlugin.py`](sirilpyBatch/Plugins/_TemplatePlugin.py) is the starting point.

## Features

- Drag-and-drop batch builder (PyQt6), with reordering (▲ ▼) and removal (✕) of steps
- Per-plugin settings generated from YAML: checkboxes, combo boxes, numbers, sliders, text, ranges
- Run a single step (**Process** / **Load** buttons) or the whole batch (**Run**)
- Named batch presets, saved to and loaded from a YAML file
- Telescope / sensor / filter profiles that plugins can read (e.g. to drive SPCC)
- Plugins are auto-discovered. A broken plugin is skipped instead of crashing the app

## Requirements

| What | Version |
| --- | --- |
| Siril | 1.4 or newer (Python scripting support) |
| Python | 3.10 or newer (Siril manages its own Python venv) |
| PyQt6, PyYAML | installed automatically on first start |

`sirilBatch.py` calls `sirilpy.ensure_installed("PyQt6", "numpy", "astropy", "pyyaml")`, so Siril installs the dependencies into its own virtual environment the first time the script runs. `sirilpy` itself comes with Siril and is not installed from PyPI.

## Installation

1. Copy `sirilBatch.py` **and** the `sirilpyBatch/` folder into a directory of your choice. Keep them side by side.
2. In Siril open **Preferences → Scripts** and add that directory to **Script Storage Directories**.
3. Click the refresh icon (or run `reloadscripts` in Siril's command line) and press **Apply**.
4. `sirilBatch.py` now appears in Siril's **Scripts** menu. You can also start it once via **Scripts → Run Script Files…** without registering the folder.

> Don't store it inside Siril's built-in scripts folder. Custom scripts there can be wiped by a Siril update.

## Quick start

1. In Siril, set the **working directory** to the folder holding your raw frames.
2. Start **sirilBatch.py** from the Scripts menu.
3. Pick your telescope in the **Telescope** drop-down.
4. Build a batch, either by choosing a saved preset in the **Batch** selector, or by dragging plugins from **Available Plugins** into the **Batch Processing** area. The order shown is the order of execution.
5. Adjust the settings of each plugin.
6. Press **Run**.

To keep a batch, type a name in the (editable) **Batch** selector and press **Save Presets**. Saving under an existing name overwrites it. The name `empty` is reserved for "no plugins".

### Buttons

| Button | Where | What it does |
| --- | --- | --- |
| **Process** | on a plugin | Runs just that plugin (shown only if the plugin implements `process()`) |
| **Load** | on a plugin | Loads that plugin's result into Siril (shown only if it implements `load()`) |
| ▲ ▼ ✕ | next to a plugin | Move up / move down / remove from the batch |
| **Save Presets** | footer | Stores the current plugin list and settings under the selected batch name |
| **Run** | footer | Runs all plugins in order |
| **Close** | footer | Disconnects from Siril and closes the window |

A plugin can appear only once per batch.

### What happens during a run

For each plugin, top to bottom:

1. `process()` is executed. An exception is logged in red in Siril's log and the batch **continues** with the next plugin.
2. Siril's working directory is reset to where it was before the plugin ran, so every plugin starts in the project root.
3. If the plugin implements `load()`, it is called so the result shows up in Siril right away.

## Working directory layout

The bundled plugins expect this structure inside the Siril working directory:

```text
<working directory>/
├── light_*.fit(s), bias_*.fit(s), dark_*.fit(s), flat_*.fit(s)   ← raw files (input)
├── lights/  biases/  darks/  flats/     ← created by "Sort Files"
├── masters/                             ← bias_master, dark_master, flat_master
└── process/                             ← converted, calibrated, registered and stacked frames
```

> ⚠️ **"Sort Files" (based on the Celestron Image-Directory) deletes and recreates `masters/` and `process/`** every time it runs. It also *moves* the matching raw files into their target folders (renamed to lowercase).

## Bundled plugins

| Title | Key | What it does |
| --- | --- | --- |
| **Sort Files** | `sorter` | Moves `light*`, `bias*`, `dark*`, `flat*` FITS files into `lights/`, `biases/`, `darks/`, `flats/`, then builds `masters/`. If a folder holds a single file (e.g. an already-stacked master from a Celestron Origin) it is just copied. With several files they are stacked. Flats are bias-calibrated first when a bias master exists. No settings. |
| **Prepare** | `calibrate` | Converts the lights, calibrates them with the bias/dark/flat masters, registers, and stacks into `process/calibration`. Options: *CFA format*, *equalize CFA*, *Debayer*, *Sigma*. Note: the stack step currently uses fixed `rej 3 3`; the *Sigma* option is not yet passed through. |
| **Color Calibration** | `color_calibration` | Works in `process/`. Optional plate solving, optional PCC (catalogue: none / apass / localgaia / gaia / nomad; *Tolerance* is used as `-bgtol` when the catalogue is `none`) and optional SPCC. SPCC takes the sensor from the selected telescope and the filter from the *Filter* combo. Saves the result as `result_calibration`. |

Todos

[ ] GraXPert Background Extraction
[ ] GraXPert Denoise
[ ] Star net
[ ] Crob

## Configuration

### Telescope profiles (`sirilpyBatch/cfg/sirilpyConfig.yaml`)

Shared, read-only-at-runtime settings that ship with the project:

```yaml
filterCfg:                       # filter name -> Siril command-line arguments
    'Dual-Band': ['-narrowband','-rwl=656.28','-rbw=18', ...]
    'No filter': ['-oscfilter=No filter']

telescopes:
  - name: 'ZWO Seestar S50'      # shown in the Telescope drop-down
    sensor: Sony IMX585
    focalLen: 250
    pixelSize: 2.9
    filter: ['No Filter (Broadband)', 'LP (Narrowband)']   # offered by "@telescope.filter"
```

To support another instrument, add an entry under `telescopes:`. If it uses a filter that isn't listed in `filterCfg:` yet, add that too. Selecting a telescope in the UI copies its entry to the `telescope` key, and plugin boxes are rebuilt so that any `@telescope.…` lists update.

### Presets (`sirilpyBatch.yaml`)

Created next to `sirilBatch.py` the first time you press **Save Presets**. It stores your batches and the selected telescope:

```yaml
Batches:
  seestar_default:
    - plugin: sorter
      config: {}
    - plugin: calibrate
      config: {cfa: false, equalize_cfa: false, debayer: true, sigma: [3, 3]}
    - plugin: color_calibration
      config: {plade: true, pcc: false, spcc: true, spcc_filter: LP (Narrowband), ...}
telescope:
  name: ZWO Seestar S50
  ...
```

Global and preset files are merged **per top-level key**, with the preset file winning. Settings are stored under each item's `Key`, so renaming a `Key` in a plugin means old presets no longer restore that value (unknown keys are ignored).

## Writing your own plugin

1. Copy `sirilpyBatch/Plugins/_TemplatePlugin.py` to a new file in the same folder. Files whose names start with `_` are **not** loaded, so the template itself never shows up in the UI. The new file must not start with `_`.
2. Edit the YAML block (key, title, settings).
3. Rename the class and implement `process()` and/or `load()`.
4. Restart the script. The plugin appears under **Available Plugins**.

```python
from sirilpy import LogColor  # type: ignore
from sirilpyBatch import BatchPlugin, BatchPluginRegistry

Plugin_Config = """
Plugin:
    Key: my_plugin          # unique id, also used in saved presets
    Title: My Plugin        # shown in the UI
Box:
    Columns: 6
Items:
    - CheckBox:
        Key: debayer
        Label: Debayer
        Default: False
    - Separator
    - IntRange:
        Key: sigma
        Label: Sigma
        Default: 3,3
"""

@BatchPluginRegistry.register(Plugin_Config)
class MyPlugin(BatchPlugin):

    result_name = "my_result"

    def process(self):
        low, high = self.get_value("sigma")
        self.cmd("cd", "process")
        self.cmd("stack", "r_pp_light", "rej", str(low), str(high), f"-out={self.result_name}")

    def load(self):
        wd = self.get_siril_wd()
        self.cmd("load", f"{wd}/process/{self.result_name}")
```

Which buttons a plugin gets depends on what it overrides: implement `process()` for a **Process** button, `load()` for a **Load** button.

### The YAML block

| Section | Option | Meaning |
| --- | --- | --- |
| `Plugin:` | `Key` | **Required.** Unique id of the plugin |
| | `Title` | Display name (defaults to the key) |
| | `Enabled` | `false` hides the plugin from the list (default `true`) |
| `Box:` | `Columns` | Number of grid columns for the settings (default `5`) |
| `Items:` | | List of settings, top to bottom / left to right |

Only `Plugin: Key` is mandatory, so a plugin without settings needs nothing else (see *Sort Files*). Names are case-insensitive and ignore spaces, `_` and `-`. The YAML is validated when the file is loaded. Mistakes are reported with the plugin and item they belong to, and that plugin is skipped (the message appears in the console output).

### Item types

| Type | Value you get from `get_value()` | Extra options |
| --- | --- | --- |
| `CheckBox` | `bool` | |
| `Text` | `str` | |
| `Int` (`Integer`) | `int` | `Min`, `Max`, `Step` |
| `Float` | `float` | `Min`, `Max`, `Step`, `Decimals` |
| `Slider` | `int` | `Min`, `Max`, `Step` |
| `ComboBox` (`Combo`) | the selected entry of `Values` | `Values` |
| `IntRange` (`Range`) | `(low, high)` ints | `Min`, `Max`, `Step` |
| `FloatRange` | `(low, high)` floats | `Min`, `Max`, `Step`, `Decimals` |
| `Separator` | – | Starts a new row and draws a divider (no `Key`) |

Options common to all items:

| Option | Meaning |
| --- | --- |
| `Key` | **Required** (except for `Separator`), unique within the plugin. Used for `get_value()` and in saved presets |
| `Label` | Text next to the control (defaults to the key) |
| `LabelPos` | `LEFT` (default) or `RIGHT` (default for checkboxes) |
| `Default` | Initial value. Ranges accept `3,3` or `[3, 3]` |
| `Tooltip` | Hover text |
| `ColSpan` | Number of grid columns the control occupies (default `1`) |

Defaults when omitted: `Min` 0, `Max` 100, `Step` 1, `Decimals` 2.

**Values from the config.** A value starting with `@` is looked up in the merged configuration using a dotted path, e.g. `Values: "@telescope.filter"` fills a combo box with the filters of the selected telescope. This works for `Values`, `Default`, `Min` and `Max`. Quote it, since YAML doesn't allow an unquoted `@`.

### What a plugin can use

| Member | Description |
| --- | --- |
| `self.cmd(*args)` | Log and run one Siril command, e.g. `self.cmd("cd", "process")` |
| `self.siril()` | The connected `sirilpy.SirilInterface` (same as `self.context.siril`) |
| `self.get_siril_wd()` | Siril's current working directory |
| `self.get_value("key")` | Current value of one of the plugin's settings |
| `self.get_config("a.b", default)` | Value from the merged global/preset config, e.g. `telescope.sensor` |
| `self.key_name`, `self.title` | The plugin's key and title |

Each plugin starts in the working directory root (see [What happens during a run](#what-happens-during-a-run)), so use paths relative to it.

## Project structure

```text
sirilBatch.py                   # entry point started by Siril
sirilpyBatch/
├── __init__.py                 # version, public API (BatchPlugin, BatchPluginRegistry, execute)
├── sirilpyBatch.py             # plugin loader + application start-up
├── cfg/
│   └── sirilpyConfig.yaml      # telescopes and filter definitions
├── Core/
│   ├── BatchProcessor.py       # main window, plugin list, drag & drop container
│   ├── BatchPlugin.py          # base class for plugins
│   ├── BatchConfig.py          # reads/writes global config and presets
│   ├── BatchContext.py         # (siril, config) handle handed to plugins
│   ├── PluginConfigBox.py      # renders a plugin's settings + Load/Process buttons
│   ├── PluginItem.py           # the setting types (checkbox, combo, range, ...)
│   ├── PluginEntry.py          # registry entry / plugin factory
│   ├── Registry.py             # @register decorator + YAML parsing/validation
│   └── Version.py
└── Plugins/
    ├── _TemplatePlugin.py      # copy this to start a new plugin (not loaded)
    ├── OriginMark2FileSorter.py
    ├── CalibratePlugin.py
    ├── ColorCalibration.py
    └── GraXPertDenoise.py      # stub
```

## Troubleshooting

- **The window never opens / "Failed to connect to Siril".** The tool must be started from a running Siril (via the Scripts menu), not from a plain terminal.
- **A plugin is missing from the list.** Look at the console output for `Skipping plugin <file>: …`. That is a YAML or import error. Also check that the file doesn't start with `_`, that it uses `@BatchPluginRegistry.register(...)`, and that its `Key` is unique.
- **The SPCC *Filter* drop-down is empty.** It is filled from the selected telescope. On a fresh install no telescope has been applied yet, so choose one in the **Telescope** drop-down (if the right one is already shown, pick another and switch back).
- **"Global config not found".** `sirilpyBatch/cfg/sirilpyConfig.yaml` is missing. Make sure the whole `sirilpyBatch/` folder was copied.
- **Presets don't persist.** They are written next to `sirilBatch.py`, so that folder must be writable.

## Development

Python ≥ 3.10 with `PyQt6` and `PyYAML`. `sirilpy` is only available inside Siril's environment, so the application can't be run standalone. The metadata in [`pyproject.toml`](pyproject.toml) is for tooling and packaging. The normal way to use the tool is the Siril installation described above. When bumping the version, update it in `pyproject.toml`, `sirilpyBatch/__init__.py` and `sirilpyBatch/Core/Version.py`.

## License

sirilpyBatch is free software, released under the GNU General Public License v3.0 or later (GPL-3.0-or-later). See LICENSE for the full text.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.