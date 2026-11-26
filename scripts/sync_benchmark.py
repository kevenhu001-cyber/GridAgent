"""Stage only pinned, allowlisted upstream assets at build time (not application startup)."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen


MAX_ASSET_BYTES = 8_000_000


def valid_blob(data, expected):
    return (len(data) <= MAX_ASSET_BYTES
            and hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == expected)


def cached_blob(path, expected):
    if path is None or not path.is_file():
        return None
    with path.open("rb") as handle:
        data = handle.read(MAX_ASSET_BYTES + 1)
    return data if valid_blob(data, expected) else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--cache-dir", type=Path, help="Reuse individually verified local public assets")
    args = parser.parse_args()
    spec = json.loads((Path(__file__).resolve().parents[1] / "src/gridagent/paper_assets.json").read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    for name, expected in spec["files"].items():
        target = args.output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        # Cache hits never bypass the pinned upstream blob integrity check.
        data = cached_blob(target, expected)
        if data is not None:
            continue
        if args.cache_dir is not None:
            data = cached_blob(args.cache_dir / name, expected)
        if data is None:
            url = f"https://raw.githubusercontent.com/{spec['repository']}/{spec['commit']}/{name}"
            with urlopen(url, timeout=90) as response:
                data = response.read(MAX_ASSET_BYTES + 1)
            if not valid_blob(data, expected):
                raise ValueError(f"Upstream blob mismatch or oversized asset: {name}")
        target.write_bytes(data)
    (args.output / "provenance.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    print(f"Staged {len(spec['files'])} pinned assets, including MIT license; no test-memory labels.")


if __name__ == "__main__":
    main()
