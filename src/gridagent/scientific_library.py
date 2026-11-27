"""Discover installed distributions without importing them on the host.

Actual callable introspection is executed in the same isolated runtime as
user-authored science programs, and counts against the run budget.
"""
import re
from importlib.metadata import distributions
from pathlib import Path

from . import plugins

DOTTED = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){0,7}")


def inventory(runtime, plugin=None):
    """Read metadata from the guest's actual mapped package roots, not host sys.path."""
    roots = [("core", Path(runtime) / "Lib" / "site-packages")]
    if plugin is not None:
        target = plugins.installed_target(plugin)
        if target is None:
            raise ValueError("Install the requested managed plugin first")
        roots.append((plugin, target))
    items = []
    for scope, path in roots:
        if not path.is_dir():
            continue
        for dist in distributions(path=[str(path)]):
            name = dist.metadata.get("Name")
            if not name or not dist.version:
                continue
            items.append({"distribution": name[:120], "version": dist.version[:120], "scope": scope})
    return sorted(items, key=lambda row: (row["distribution"].casefold(), row["scope"]))[:500]


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
