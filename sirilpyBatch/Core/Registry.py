# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Nikolas Pommerening
# Contact: nikodemus.p@gmx.at
#
from dataclasses import dataclass, fields
import textwrap
from typing import Any, Optional, Type, Union

import yaml

from .BatchPlugin import BatchPlugin
from .PluginEntry import BatchPluginEntry
from .PluginItem import ITEM_TYPES, PluginItem, SeparatorItem


_PLUGIN_SECTION_OPTIONS = {"key": "key", "title": "title", "enabled": "enabled"}
_BOX_SECTION_OPTIONS = {"columns": "columns"}

@dataclass
class PluginSpec:
    """Everything a plugin's YAML document describes."""

    key: str
    title: str
    items: list[PluginItem]
    columns: int = 5
    enabled: bool = True
    
def _norm(name: Any) -> str:
    """Case-insensitive comparison form; ignores ``_``, ``-`` and spaces."""
    return str(name).strip().lower().replace("_", "").replace("-", "").replace(" ", "")

def _load_yaml(spec: Any, source: str) -> Any:
    """Parse ``spec`` if it is YAML text (dedented first); pass anything else through."""
    if not isinstance(spec, str):
        return spec
    try:
        return yaml.safe_load(textwrap.dedent(spec))
    except yaml.YAMLError as error:
        raise ValueError(f"{source}: invalid YAML: {error}") from error
# Short spellings accepted in YAML -> real dataclass field name.
_OPTION_ALIASES = {"min": "minimum", "max": "maximum", "labelposition": "labelpos"}

def _build_item(type_name: Any, options: Any, where: str) -> PluginItem:
    """Create one PluginItem from its YAML type name and options mapping."""
    normalized = _norm(type_name)
    if normalized.endswith("item"):  # allow "CheckboxItem" as well as "Checkbox"
        normalized = normalized[: -len("item")]
    item_cls = ITEM_TYPES.get(normalized)
    if item_cls is None:
        raise ValueError(
            f"{where}: unknown item type '{type_name}' "
            f"(available: {', '.join(sorted(ITEM_TYPES))})"
        )

    if options is None:
        options = {}
    if not isinstance(options, dict):
        raise ValueError(f"{where}: options of '{type_name}' must be a mapping, got {options!r}")

    field_names = {f.name for f in fields(item_cls)}
    valid = {_norm(name): name for name in field_names}
    for alias, target in _OPTION_ALIASES.items():
        if target in field_names:
            valid[alias] = target

    kwargs: dict[str, Any] = {}
    for raw_key, value in options.items():
        name = valid.get(_norm(raw_key))
        if name is None:
            raise ValueError(
                f"{where}: unknown option '{raw_key}' for '{type_name}' "
                f"(valid: {', '.join(sorted(field_names))})"
            )
        kwargs[name] = value

    try:
        return item_cls(**kwargs)
    except ValueError as error:
        raise ValueError(f"{where}: {error}") from error


def parse_plugin_items(
    spec: Union[str, dict, list, None], source: str = "plugin"
) -> list[PluginItem]:
    """
    Turn a plugin's item description into a list of ``PluginItem`` objects.

    ``spec`` may be YAML text (with a top-level ``Items:`` list), an already parsed
    dict/list, or - for backwards compatibility - a list of ready-made ``PluginItem``
    objects (which is passed through unchanged). Raises ``ValueError`` with a message
    naming ``source`` and the offending item if anything is malformed.
    """
    spec = _load_yaml(spec, source)

    if isinstance(spec, dict):
        matches = [value for key, value in spec.items() if _norm(key) == "items"]
        if not matches:
            raise ValueError(f"{source}: YAML must contain a top-level 'Items:' list")
        spec = matches[0]

    if spec is None:
        return []
    if not isinstance(spec, list):
        raise ValueError(f"{source}: 'Items' must be a list, got {type(spec).__name__}")

    items: list[PluginItem] = []
    seen_keys: set[str] = set()

    for index, element in enumerate(spec, start=1):
        where = f"{source}, item #{index}"

        if isinstance(element, PluginItem):
            item = element
        elif isinstance(element, str):  # bare "- Separator"
            item = _build_item(element, None, where)
        elif isinstance(element, dict) and len(element) == 1:  # "- CheckBox: {...}"
            ((type_name, options),) = element.items()
            item = _build_item(type_name, options, where)
        else:
            raise ValueError(
                f"{where}: expected 'TypeName' or a single 'TypeName: {{options}}' mapping, "
                f"got {element!r}"
            )

        if not isinstance(item, SeparatorItem):
            if item.key is None or str(item.key).strip() == "":
                raise ValueError(f"{where}: {type(item).__name__} needs a 'Key'")
            item.key = str(item.key)
            if item.key in seen_keys:
                raise ValueError(f"{where}: duplicate key '{item.key}'")
            seen_keys.add(item.key)
            if item.label is None:
                item.label = item.key

        items.append(item)

    return items
    
def _read_section(value: Any, section: str, allowed: dict[str, str], source: str) -> dict[str, Any]:
    """Return ``{option: value}`` for a ``Plugin:`` / ``Box:`` section, rejecting unknown options."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{source}: '{section}' must be a mapping of options")

    result: dict[str, Any] = {}
    for raw_key, option_value in value.items():
        name = allowed.get(_norm(raw_key))
        if name is None:
            raise ValueError(
                f"{source}: unknown option '{raw_key}' in '{section}' "
                f"(valid: {', '.join(sorted(allowed.values()))})"
            )
        result[name] = option_value
    return result

def parse_plugin_spec(spec: Union[str, dict], source: str = "plugin") -> PluginSpec:
    """
    Parse a plugin's YAML document (``Plugin:`` / ``Box:`` / ``Items:`` sections) into a
    ``PluginSpec``. Only ``Plugin: Key`` is mandatory. Raises ``ValueError`` with a message
    naming the plugin and the offending section/item if anything is malformed.
    """
    data = _load_yaml(spec, source)
    if not isinstance(data, dict):
        raise ValueError(
            f"{source}: expected a YAML mapping with 'Plugin:', 'Box:' and 'Items:' sections"
        )

    sections: dict[str, Any] = {}
    for name, value in data.items():
        normalized = _norm(name)
        if normalized not in ("plugin", "box", "items"):
            raise ValueError(
                f"{source}: unknown section '{name}' (valid: Plugin, Box, Items)"
            )
        sections[normalized] = value

    plugin = _read_section(sections.get("plugin"), "Plugin", _PLUGIN_SECTION_OPTIONS, source)
    key = plugin.get("key")
    if key is None or str(key).strip() == "":
        raise ValueError(f"{source}: the 'Plugin' section needs a 'Key'")
    key = str(key).strip()
    source = f"plugin '{key}'"  # from here on, errors name the plugin

    title = plugin.get("title")
    title = key if title is None else str(title)

    enabled = plugin.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError(f"{source}: 'Enabled' must be true or false, got {enabled!r}")

    box = _read_section(sections.get("box"), "Box", _BOX_SECTION_OPTIONS, source)
    columns = box.get("columns", 5)
    if isinstance(columns, bool) or not isinstance(columns, int) or columns < 1:
        raise ValueError(f"{source}: 'Columns' must be a positive integer, got {columns!r}")

    items = parse_plugin_items(sections.get("items"), source)

    return PluginSpec(key=key, title=title, items=items, columns=columns, enabled=enabled)

class BatchPluginRegistry:
    """
    Global registry of all available plugin types.

    Plugin modules register themselves with the ``@BatchPluginRegistry.register(...)``
    class decorator at import time (see ``load_plugins``), so simply importing a
    plugin module is enough to make it available in the UI.
    """

    _entries: list[BatchPluginEntry] = []

    # ------------------------------------------------------------------
    @classmethod
    def register(
        cls,
        spec: Union[str, dict, None] = None,
        *,
        key: Optional[str] = None,
        title: Optional[str] = None,
        items: Union[str, dict, list[PluginItem], None] = None,
        columns: int = 5,
        enabled: bool = True,
    ):
        """
        Class decorator: wraps a ``BatchPlugin`` subclass and registers its metadata.

        Normal use passes one YAML document that describes the whole plugin (see
        ``parse_plugin_spec``)::

            @BatchPluginRegistry.register(calibration_items)
            class CalibratePlugin(BatchPlugin): ...

        The YAML is parsed and validated right here, so a mistake is reported when the
        plugin module is loaded. The older keyword form
        ``register(key=..., title=..., items=..., columns=...)`` still works.
        """
        if spec is not None:
            plugin_spec = parse_plugin_spec(spec)
        elif key is not None:
            plugin_spec = PluginSpec(
                key=key,
                title=title if title is not None else key,
                items=parse_plugin_items(items, source=f"plugin '{key}'"),
                columns=columns,
                enabled=enabled,
            )
        else:
            raise TypeError(
                "register() needs a YAML plugin definition, e.g. "
                "@BatchPluginRegistry.register(calibration_items)"
            )

        def decorator(plugin_cls: Type[BatchPlugin]):
            cls._entries.append(
                BatchPluginEntry(
                    plugin_cls=plugin_cls,
                    key=plugin_spec.key,
                    title=plugin_spec.title,
                    items=plugin_spec.items,
                    columns=plugin_spec.columns,
                    enabled=plugin_spec.enabled,
                )
            )
            return plugin_cls

        return decorator

    @classmethod
    def all(cls) -> list[BatchPluginEntry]:
        """Return every registered plugin entry sorted by title."""
        return sorted(
            cls._entries,
            key=lambda entry: (entry.title or "").lower(),
        )

    # ------------------------------------------------------------------
    @classmethod
    def get(
        cls,
        key: str,
    ) -> Optional[BatchPluginEntry]:
        """Look up a registered entry by its key, or None if not found."""

        for entry in cls._entries:

            if entry.key == key:
                return entry

        return None

    # ------------------------------------------------------------------
    @classmethod
    def clear(cls):
        """Remove all registered entries (mainly useful for tests)."""
        cls._entries.clear()