"""Site plugins for ui3.

Core BioQueue stays generic. Lab-specific views (WandB, Dec, …) live outside git:
register them from ``settings.UI3_PLUGINS`` or drop a module in
``ui3/plugins/local/`` (that directory is gitignored except the README).

A plugin is a ``Plugin`` subclass with optional ``urlpatterns``, ``nav_items``,
and ``shortcut_presets``. Instantiating and calling ``register()`` at import
time is enough. Job cards still show plugin features only through protocol
shortcuts that point at those URLs.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil

from django.conf import settings

logger = logging.getLogger(__name__)

_plugins = []
_loaded = False


class Plugin:
    """Extension point for a site-specific ui3 feature."""

    name = "plugin"

    def urlpatterns(self):
        """Django ``path()`` / ``re_path()`` objects, mounted under ``/ui/``."""
        return []

    def nav_items(self, request):
        """Optional header links: ``{href, label, icon?, active?}``."""
        return []

    def shortcut_presets(self):
        """Protocol-shortcut picker rows: ``{label, href_template, params_template?}``.

        Choosing one creates a normal ProtocolShortcut. Job cards then show it
        the same way as a hand-typed shortcut. Use ``{id}`` for the job id.
        """
        return []


def register(plugin):
    if plugin is None:
        return plugin
    for existing in _plugins:
        if existing is plugin:
            return plugin
        if getattr(existing, "name", None) and existing.name == getattr(plugin, "name", None):
            return plugin
    _plugins.append(plugin)
    return plugin


def unregister(name_or_plugin):
    remaining = []
    for plugin in _plugins:
        if plugin is name_or_plugin or getattr(plugin, "name", None) == name_or_plugin:
            continue
        remaining.append(plugin)
    _plugins[:] = remaining


def reset():
    """Drop registered plugins. Tests only; does not unload imported modules."""
    _plugins.clear()
    global _loaded
    _loaded = False


def get_plugins():
    return list(_plugins)


def urlpatterns():
    patterns = []
    for plugin in _plugins:
        try:
            patterns.extend(plugin.urlpatterns() or [])
        except Exception:
            logger.exception("ui3 plugin %s urlpatterns failed", getattr(plugin, "name", plugin))
    return patterns


def nav_items(request):
    items = []
    for plugin in _plugins:
        try:
            items.extend(plugin.nav_items(request) or [])
        except Exception:
            logger.exception("ui3 plugin %s nav_items failed", getattr(plugin, "name", plugin))
    return items


def shortcut_presets():
    items = []
    for plugin in _plugins:
        try:
            raw = plugin.shortcut_presets() or []
        except Exception:
            logger.exception("ui3 plugin %s shortcut_presets failed", getattr(plugin, "name", plugin))
            continue
        for preset in raw:
            if not isinstance(preset, dict):
                continue
            label = str(preset.get("label") or "").strip()
            href = str(preset.get("href_template") or "").strip()
            if not label or not href:
                continue
            items.append({
                "label": label,
                "href_template": href,
                "params_template": str(preset.get("params_template") or "").strip(),
                "plugin": getattr(plugin, "name", "") or "",
            })
    return items


def _import_module(dotted):
    try:
        importlib.import_module(dotted)
    except Exception:
        logger.exception("ui3 plugin module %s failed to import", dotted)


def autodiscover():
    """Import ``UI3_PLUGINS`` modules and ``ui3.plugins.local.*`` once."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    for dotted in getattr(settings, "UI3_PLUGINS", None) or []:
        if dotted:
            _import_module(str(dotted))
    try:
        from ui3.plugins import local as local_pkg
    except Exception:
        local_pkg = None
    if local_pkg is not None:
        prefix = local_pkg.__name__ + "."
        for info in pkgutil.iter_modules(getattr(local_pkg, "__path__", [])):
            if not info.name or info.name.startswith("_"):
                continue
            _import_module(prefix + info.name)
    _import_module("ui3.plugins.legacy")
