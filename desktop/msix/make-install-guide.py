"""Create a branded offline installation landing page for the exact built MSIX."""
import html
import json
import sys
from pathlib import Path


def render(directory):
    info = json.loads((directory / "package-info.json").read_text(encoding="utf-8-sig"))
    packages = list(directory.glob("*.msix"))
    if len(packages) != 1:
        raise ValueError("Expected exactly one MSIX")
    filename = html.escape(packages[0].name, quote=True)
    publisher = html.escape(info["publisher"])
    version = html.escape(info["version"])
    size = f'{info["bytes"] / (1024 ** 2):.1f} MiB'
    development = bool(info["development"])
    notice = (
        '<aside><strong>Development build</strong><p>This package uses a temporary self-signed certificate. '
        'Use only on a dedicated test machine. Verify the certificate thumbprint and SHA-256 checksum. '
        'An administrator must explicitly trust the public certificate before installing. '
        'Do not change trust settings on an untrusted machine.</p>'
        '<p><a href="GridAgent-Development.cer">Public certificate</a> · '
        '<a href="package-info.json">Certificate identity and thumbprint</a></p></aside>'
        if development else
        '<p>Verify the publisher and signature in Windows App Installer before continuing.</p>'
    )
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Install GridAgent — TopoDrive</title>
<style>
:root{{color-scheme:light dark;--bg:#fafafa;--fg:#171717;--muted:#606060;--border:#ddd;--panel:#fff;--button:#202020;--buttontext:#fff}}
@media(prefers-color-scheme:dark){{:root{{--bg:#181818;--fg:#eee;--muted:#aaa;--border:#444;--panel:#222;--button:#eee;--buttontext:#171717}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 "Segoe UI",system-ui,sans-serif}}
main{{max-width:740px;margin:auto;padding:48px 24px}}header{{font-size:13px;font-weight:600;letter-spacing:.12em}}
.brand{{display:block;width:180px;height:auto;margin:20px 0;border-radius:8px}}h1{{font-size:42px;line-height:1.15;letter-spacing:-.04em;margin:28px 0 8px}}h2{{font-size:19px;margin:0 0 8px}}
p{{margin:0 0 12px}}.muted,small{{color:var(--muted)}}.card{{border:1px solid var(--border);border-radius:14px;background:var(--panel);padding:24px;margin:26px 0}}
.action{{display:inline-block;background:var(--button);color:var(--buttontext);padding:11px 20px;border-radius:8px;text-decoration:none;font-weight:600}}
a{{color:inherit;text-underline-offset:3px}}a:focus-visible{{outline:2px solid #4688da;outline-offset:4px}}
aside{{border-left:3px solid #ba8620;padding:12px 16px;margin:16px 0}}ol{{padding-left:22px}}li{{margin-bottom:12px}}
footer{{border-top:1px solid var(--border);padding-top:18px;margin-top:30px;color:var(--muted);font-size:13px}}
</style></head><body><main>
<header>TOPODRIVE</header>
<img class="brand" src="GridAgent-logo.png" alt="GridAgent approved logo">
<h1>Install GridAgent</h1><p class="muted">AI-assisted power system research, on your Windows desktop.</p>
<section class="card"><h2>Windows x64 · MSIX</h2>
<p class="muted">Package {version} · {size} · Windows 10 version 2004 or later</p>
<p>Includes the native application, private Python runtime and core simulation tools.</p>
{notice}
<p><a class="action" href="{filename}">Open MSIX package</a></p>
<p><small>Signed publisher: {publisher}. <a href="SHA256SUMS.txt">SHA-256 checksum</a></small></p></section>
<section><h2>Getting started</h2><ol>
<li><strong>Install.</strong> Open the MSIX in this folder. Windows App Installer displays the publisher and requests installation approval. If your browser does not open local packages, double-click <code>{filename}</code> in File Explorer.</li>
<li><strong>Launch.</strong> Open GridAgent from the Start menu.</li>
<li><strong>Set up.</strong> Choose a research workspace and optionally configure an AI model in the native first-run guide. Offline tools need no API key.</li>
</ol></section>
<footer>Developed by TopoDrive · Lead developer Adex Hu · GPL-3.0-or-later</footer>
</main></body></html>"""
    (directory / "Install GridAgent.html").write_text(page, encoding="utf-8")


if __name__ == "__main__":
    render(Path(sys.argv[1]))
