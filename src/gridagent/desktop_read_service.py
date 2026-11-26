"""Versioned local metadata/read service; never dispatches provider or solver mutations."""
import json
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

from .desktop_bridge import dispatch

VERSION = 1
MAX_REQUEST = 65536
MAX_RESPONSE = 16 * 1024 * 1024
READ_ACTIONS = {
    "initialize": set(),
    "refresh": set(),
    "history": {"session", "presentation"},
    "waveform": {"run"},
    "analysis-charts": {"run"},
    "waveform-overlay": {"runs"},
    "topology": {"run"},
    "artifact-preview": {"run"},
}


def serve(root, source, output, *, handler=dispatch):
    """One request at a time; every response carries a version and request ID."""
    def send(identifier, kind, data):
        encoded = json.dumps({"version": VERSION, "id": identifier, "kind": kind, "data": data},
                             ensure_ascii=True, allow_nan=False)
        if len(encoded) > MAX_RESPONSE:
            raise ValueError("Response exceeds desktop service limit")
        print(encoded, file=output, flush=True)

    while True:
        line = source.readline(MAX_REQUEST + 1)
        if not line:
            return
        # Close the lane rather than attempt to resynchronize a truncated frame.
        if len(line) > MAX_REQUEST or not line.endswith("\n"):
            return
        identifier = None
        try:
            frame = json.loads(line)
            identifier = frame["id"]
            if not isinstance(identifier, str) or not re.fullmatch(r"[a-f0-9]{32}", identifier):
                return
            if frame["version"] != VERSION or set(frame) != {"version", "id", "request"}:
                raise ValueError("Unsupported protocol")
            request = frame["request"]
            action = request["action"]
            if action not in READ_ACTIONS or not set(request) <= READ_ACTIONS[action] | {"action"}:
                raise ValueError("Unsupported read operation")
            with redirect_stdout(sys.stderr):
                handler(root, request, lambda kind, data: send(identifier, kind, data))
        except Exception as exc:  # noqa: BLE001 - transport boundary, no sensitive exception content
            if identifier is None:
                return
            send(identifier, "error", type(exc).__name__ + ": read operation failed")
            send(identifier, "done", False)
        else:
            send(identifier, "done", True)


def main():
    if len(sys.argv) != 2:
        return 2
    serve(Path(sys.argv[1]), sys.stdin, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
