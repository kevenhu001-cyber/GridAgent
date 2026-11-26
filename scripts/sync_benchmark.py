"""Stage only pinned, allowlisted upstream assets at build time (not application startup)."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    spec = json.loads((Path(__file__).resolve().parents[1] / "src/gridagent/paper_assets.json").read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    for name, expected in spec["files"].items():
        target = args.output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://raw.githubusercontent.com/{spec['repository']}/{spec['commit']}/{name}"
        with urlopen(url, timeout=90) as response:
            data = response.read(8_000_001)
        if len(data) > 8_000_000:
            raise ValueError(f"Asset too large: {name}")
        actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if actual != expected:
            raise ValueError(f"Upstream blob mismatch: {name}")
        target.write_bytes(data)
    (args.output / "provenance.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    print(f"Staged {len(spec['files'])} pinned assets, including MIT license; no test-memory labels.")


if __name__ == "__main__":
    main()
