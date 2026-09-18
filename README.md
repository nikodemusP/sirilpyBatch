# Siril Batch-Processing

This python scripts apply a configurable batch-script for Siril

## Available Plugins

+ Sort Files from the Celestron Origin Smart Mark II
+ Calibrate Files

## How to add Plugins

Every Plugin-Box has a set of items to be configured

```python
calibrate_items = [
    CheckboxItem(
        key="cfa",          
        label="CFA format",
        colspan=2,
        default=False),
]

@BatchPluginRegistry.register(key="calibrate", title="Calibrate", items=calibrate_items, columns=6)
class CalibratePlugin(BatchPlugin):

    result_name = "calibration"

    def process(self):
        # ── 1) Convert Lights ─────────────────────────────

    def load(self):
        # ── load result-file-name ─────────────────────────────
        wd = self.get_siril_wd()
        self.cmd("load", f"{wd}/process/{self.result_name}")
```
+ Items

|||
|-|-|
|key|key name of the item
|label|label of the item
|colspan|columns used by the item
|default|default value of the item

+ Registry

|||
|-|-|
|key|key name of the plugin
|title|Title of the plugin
|items|defined items
|columns|count of columns within the box

+ process will execute the function

```
    def process(self):
```

+ load is used to reload the process files

```
    def load(self):
```
