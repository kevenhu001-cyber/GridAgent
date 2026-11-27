"""Discover installed distributions without importing them on the host.

Actual callable introspection is executed in the same isolated runtime as
user-authored science programs, and counts against the run budget.
"""
import re
from contextlib import ExitStack, contextmanager
from importlib.metadata import distributions
from pathlib import Path

from filelock import FileLock

from . import plugins

DOTTED = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){0,7}")


MAX_PLUGINS = 4
MAX_DISTRIBUTIONS = 2000


def selected_plugins(plugin=None, plugin_ids=None):
    """Validate first-party IDs and preserve explicit import precedence."""
    if plugin is not None and plugin_ids is not None:
        raise ValueError("Use either plugin or plugin_ids, not both")
    ids = [plugin] if plugin is not None else ([] if plugin_ids is None else plugin_ids)
    if not isinstance(ids, list) or len(ids) > MAX_PLUGINS:
        raise ValueError("Select at most four managed plugins")
    for item in ids:
        if not isinstance(item, str):
            raise ValueError("Plugin IDs must be strings")
        plugins.spec(item)
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate managed plugin ID")
    return tuple(ids)


@contextmanager
def managed_targets(ids):
    """Pin active managed generations with globally ordered plugin locks."""
    with ExitStack() as stack:
        if ids:
            root = plugins.plugin_root()
            root.mkdir(parents=True, exist_ok=True)
            for item in sorted(ids):
                stack.enter_context(FileLock(str(root / (item + ".lock")), timeout=0))
        targets = {}
        for item in ids:
            target = plugins.installed_target(item)
            if target is None:
                raise ValueError(f"Install managed plugin {item} before using its native API")
            targets[item] = target
        yield targets


def environment_inventory(runtime, targets):
    """Inspect metadata only; do not import packages or silently resolve conflicts."""
    roots = [("core", Path(runtime) / "Lib" / "site-packages"), *targets.items()]
    items = []
    for scope, path in roots:
        if not path.is_dir():
            continue
        for dist in distributions(path=[str(path)]):
            name = dist.metadata.get("Name")
            if not name or not dist.version:
                continue
            if len(items) >= MAX_DISTRIBUTIONS:
                raise ValueError("Scientific environment distribution limit exceeded")
            items.append({"distribution": name[:120], "version": dist.version[:120], "scope": scope})
    items.sort(key=lambda row: (row["distribution"].casefold(), row["scope"], row["version"]))
    groups = {}
    for row in items:
        key = re.sub(r"[-_.]+", "-", row["distribution"].casefold())
        groups.setdefault(key, []).append(row)
    conflicts = [{"distribution": key, "versions": rows} for key, rows in sorted(groups.items())
                 if len({row["version"] for row in rows}) > 1]
    return {"distributions": items, "conflicts": conflicts,
            "plugin_ids": list(targets), "import_precedence": ["project", *targets, "core"],
            "scope": "distribution metadata only; not proof of import, ABI or numerical compatibility"}


def inventory(runtime, plugin=None):
    """Legacy inventory view for single-plugin consumers."""
    with managed_targets(selected_plugins(plugin)) as targets:
        return environment_inventory(runtime, targets)["distributions"][:500]


def preflight(runtime, targets):
    info = environment_inventory(runtime, targets)
    if len(targets) > 1 and info["conflicts"]:
        names = ", ".join(row["distribution"] for row in info["conflicts"][:12])
        raise ValueError("Scientific dependency conflict: " + names
                         + "; inspect library metadata or use separate runs")
    return info


def probe_source(module, symbol=None):
    if not isinstance(module, str) or len(module) > 120 or not DOTTED.fullmatch(module):
        raise ValueError("Use a dotted Python module name")
    if symbol is not None and (not isinstance(symbol, str) or len(symbol) > 120 or not DOTTED.fullmatch(symbol)):
        raise ValueError("Use a dotted attribute name relative to the module")
    # Only guest code imports the requested module. It is not evaluated by the host.
    return f"""import importlib
import inspect
import json
import os
from pathlib import Path

module = importlib.import_module({module!r})
symbol = {symbol!r}
obj = module
if symbol is not None:
    for name in symbol.split("."):
        obj = getattr(obj, name)
try:
    signature = str(inspect.signature(obj))[:4000]
except (ValueError, TypeError):
    signature = None
doc = (inspect.getdoc(obj) or "")[:12000]
public = sorted(name for name in dir(obj) if not name.startswith("_"))[:200]
result = {{"module": module.__name__, "symbol": symbol,
           "module_file": str(getattr(module, "__file__", ""))[:500],
           "module_version": str(getattr(module, "__version__", "unknown"))[:120],
           "signature": signature, "docstring": doc, "public_members": public,
           "scope": "runtime introspection; documentation is untrusted reference data"}}
path = Path(os.environ["GRIDAGENT_OUTPUT_DIR"]) / "api.json"
path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
print("API inspection saved to api.json")
"""
