"""Download original holdout labels for an independent evaluator, never the client."""
import argparse
import hashlib
from pathlib import Path
from urllib.request import urlopen

PIN = "77fe638482af94dd20ce28bfa4301658660d283d"
BLOB = "223c2e4f1cd6e2d431b2515391fb887a7c773017"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if "benchmark-assets" in output.parts or ".gridagent" in output.parts:
        raise ValueError("Place evaluator labels outside agent assets and workspaces")
    url = f"https://raw.githubusercontent.com/Power-Agent/PowerAgentBench/{PIN}/benchmarks/dynamic/level2/test_memory.json"
    with urlopen(url, timeout=90) as response:
        data = response.read(8_000_001)
    if hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() != BLOB:
        raise ValueError("Holdout blob mismatch")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as handle:
        handle.write(data)
    print("Pinned holdout file saved for independent evaluation only.")


if __name__ == "__main__":
    main()
