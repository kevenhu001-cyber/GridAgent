"""Version-aware, offline scientific reference retrieval; never imports solver code."""
import ast
import re
from importlib.metadata import distributions
from pathlib import Path

from . import scientific_workspace as ws
from .knowledge import tokens
from .knowledge_store import reference_rows
from .official_knowledge import official_rows
from .scientific_library import DOTTED, environment_inventory

MAX_SOURCE = 512 * 1024
MAX_MATCHES = 8


def canonical(name):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", name):
        raise ValueError("Use a distribution name, not a path or URL")
    return re.sub(r"[-_.]+", "-", name.casefold())


def selected_distribution(runtime, targets, name):
    """Resolve declared distribution precedence, not the actual Python import."""
    key = canonical(name)
    roots = [*targets.items(), ("core", Path(runtime) / "Lib" / "site-packages")]
    for scope, path in roots:
        matches = [dist for dist in distributions(path=[str(path)])
                   if dist.metadata.get("Name") and canonical(dist.metadata["Name"]) == key]
        if len(matches) > 1:
            raise ValueError("Multiple metadata records for one distribution in a selected scope")
        if matches:
            return scope, Path(path), matches[0]
    raise ValueError("Distribution is not installed in the selected scientific environment")


def search_references(root, runtime, targets, distribution, query, limit=5):
    """Return only exact-version references; never treat summaries as verified signatures."""
    if not isinstance(query, str) or not 1 <= len(query) <= 240 or not 1 <= limit <= MAX_MATCHES:
        raise ValueError("Invalid documentation query or result limit")
    key = canonical(distribution)
    info = environment_inventory(runtime, targets)
    scope, _, dist = selected_distribution(runtime, targets, distribution)
    version = dist.version
    rows = [row for row in [*official_rows(), *reference_rows(root)]
            if row.get("backend") and canonical(row["backend"]) == key]
    words = set(tokens(query))
    ranked = []
    for row in rows:
        symbol = row.get("option") or row["function"]
        haystack = " ".join([row["function"], symbol, row["description"]])
        score = len(words & set(tokens(haystack)))
        if query.casefold() in {symbol.casefold(), row["function"].casefold()}:
            score += 100
        if score and row["version"] == version:
            ranked.append((score, row["id"], row))
    hits = [row for _, _, row in sorted(ranked, key=lambda item: (-item[0], item[1]))[:limit]]
    return {"status": "ok", "distribution": key, "installed_version": version, "distribution_scope": scope,
            "references": hits, "other_reference_versions": sorted({row["version"] for row in rows
                                                                     if row["version"] != version})[:12],
            "dependency_conflicts": [row for row in info["conflicts"] if row["distribution"] == key],
            "scope": "exact-version attributed reference text; not a verified runtime signature",
            "next_action": "For missing references inspect installed source or actual sandbox API"}


def _definitions(body, parts):
    """Follow only lexical class scopes; do not resolve imports or evaluate expressions."""
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == parts[0]:
            if len(parts) == 1:
                yield node
            elif isinstance(node, ast.ClassDef):
                yield from _definitions(node.body, parts[1:])


def inspect_source(runtime, targets, distribution, module, symbol=None):
    """Inspect a recorded .py source file from a selected installed distribution."""
    if not isinstance(module, str) or len(module) > 120 or not DOTTED.fullmatch(module):
        raise ValueError("Use a dotted Python module name")
    if symbol is not None and (not isinstance(symbol, str) or len(symbol) > 120 or not DOTTED.fullmatch(symbol)):
        raise ValueError("Use a dotted attribute name relative to the module")
    scope, base, dist = selected_distribution(runtime, targets, distribution)
    stem = module.replace(".", "/")
    candidates = (stem + ".py", stem + "/__init__.py")
    recorded = {str(item).replace("\\", "/") for item in (dist.files or ())}
    source_path = next((item for item in candidates if item in recorded), None)
    result = {"status": "ok", "distribution": canonical(distribution), "installed_version": dist.version,
              "distribution_scope": scope, "module": module, "symbol": symbol,
              "scope": "static installed source; not actual import resolution or runtime signature"}
    if source_path is None:
        return {**result, "definitions": [], "availability": "source_unavailable",
                "next_action": "Use inspect_native_api inside the authorized sandbox"}
    source = ws.bounded_bytes(ws.scoped(base, source_path), MAX_SOURCE)
    try:
        tree = ast.parse(source, filename=source_path)
        if symbol is None:
            definitions = [{"name": node.name, "kind": type(node).__name__, "line": node.lineno}
                           for node in tree.body
                           if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                           and not node.name.startswith("_")][:100]
            result["module_docstring"] = (ast.get_docstring(tree) or "")[:6000]
        else:
            definitions = []
            for node in _definitions(tree.body, symbol.split(".")):
                if len(definitions) >= MAX_MATCHES:
                    break
                signature = None
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    signature = "(" + ast.unparse(node.args) + ")"
                    if node.returns is not None:
                        signature += " -> " + ast.unparse(node.returns)
                definitions.append({"name": node.name, "kind": type(node).__name__, "line": node.lineno,
                                    "signature": signature[:2000] if signature else None,
                                    "docstring": (ast.get_docstring(node) or "")[:6000]})
    except (SyntaxError, ValueError, RecursionError):
        return {**result, "definitions": [], "availability": "source_parse_failed",
                "next_action": "Use inspect_native_api inside the authorized sandbox"}
    return {**result, "source_path": source_path, "source_sha256": ws.sha(source), "definitions": definitions,
            "availability": "static_definitions" if definitions else "definition_unavailable",
            "next_action": "Verify re-exports, decorators, compiled APIs and imports with inspect_native_api"}
