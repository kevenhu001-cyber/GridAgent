"""Reject implicit icon conversion and unreviewed symbols before WinUI publish.

The supported subset is intentionally small. When adding a SymbolIcon, verify
the name against Microsoft.UI.Xaml.Controls.Symbol in the pinned Windows App
SDK, then extend this list. FontIcon and other explicit icon types are allowed.
The real window startup smoke remains the runtime authority.
"""
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1] / "GridAgent.WinUI"
SYMBOLS = {
    "Add", "AllApps", "Clock", "Comment", "Document", "Library", "List",
    "Manage", "OpenFile", "Play", "Read", "Refresh", "Repair", "Send", "View",
}

def check():
    errors = []
    for path in sorted(ROOT.rglob("*.xaml")):
        if {"bin", "obj"} & set(path.relative_to(ROOT).parts):
            continue
        for node in ET.parse(path).iter():
            tag = node.tag.rsplit("}", 1)[-1]
            if tag in {"NavigationViewItem", "AppBarButton"} and "Icon" in node.attrib:
                errors.append(f"{path.name}: use an explicit icon element on {tag}")
            if tag == "SymbolIcon":
                symbol = node.get("Symbol")
                if symbol not in SYMBOLS:
                    errors.append(f"{path.name}: unreviewed SymbolIcon {symbol!r}")
    if errors:
        raise SystemExit("\n".join(errors))
    print("WinUI XAML icon contracts passed.")

if __name__ == "__main__":
    check()
