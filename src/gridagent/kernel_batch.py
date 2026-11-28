"""Jupyter cells within one isolated scientific job, not a host fallback."""
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

MAX_CELLS = 8
MAX_SOURCE = 24000
MAX_OUTPUT = 12000


def validate_cells(cells):
    if not isinstance(cells, list) or not 1 <= len(cells) <= MAX_CELLS:
        raise ValueError("Provide one to eight Python cells")
    if any(not isinstance(cell, str) or not cell.strip() or "\x00" in cell for cell in cells):
        raise ValueError("Cells must contain nonempty text without NUL")
    if sum(len(cell.encode("utf-8")) for cell in cells) > MAX_SOURCE:
        raise ValueError("Kernel source exceeds 24000 bytes")


def launcher_source(cells):
    validate_cells(cells)
    return (Path(__file__).read_text(encoding="utf-8") +
            "\nif __name__ == '__main__':\n    sys.exit(run_cells(" + repr(cells) +
            ", Path(os.environ['GRIDAGENT_OUTPUT_DIR'])))\n").encode("utf-8")


def run_cells(cells, output):
    """Guest-only driver; tests invoke it with fixed trusted fixtures."""
    from jupyter_client import KernelManager
    from jupyter_client.kernelspec import KernelSpecManager

    validate_cells(cells)
    rows = []
    outcome = "ok"
    with TemporaryDirectory(prefix="gridagent-kernel-") as temp:
        root = Path(temp)
        spec = root / "specs" / "gridagent-python"
        spec.mkdir(parents=True)
        (spec / "kernel.json").write_text(json.dumps({
            "argv": [sys.executable, "-I", "-B", "-m", "ipykernel_launcher", "-f", "{connection_file}"],
            "display_name": "GridAgent Python", "language": "python",
        }), encoding="utf-8")
        manager = KernelManager(
            kernel_name="gridagent-python",
            kernel_spec_manager=KernelSpecManager(kernel_dirs=[str(spec.parent)], ensure_native_kernel=False),
            connection_file=str(root / "connection.json"),
            ip="127.0.0.1",
        )
        client = None
        try:
            manager.start_kernel(cwd=str(Path.cwd()))
            client = manager.client()
            client.start_channels()
            client.wait_for_ready(timeout=20)
            for index, source in enumerate(cells):
                chunks = []
                remaining = MAX_OUTPUT

                def receive(message):
                    nonlocal remaining
                    kind = message["header"]["msg_type"]
                    content = message["content"]
                    if kind == "stream":
                        value = content.get("text", "")
                    elif kind in {"execute_result", "display_data"}:
                        value = content.get("data", {}).get("text/plain", "")
                    elif kind == "error":
                        value = content.get("ename", "") + ": " + content.get("evalue", "")
                    else:
                        return
                    if isinstance(value, str) and remaining > 0:
                        part = value.encode("utf-8", errors="replace")[:remaining]
                        chunks.append(part.decode("utf-8", errors="ignore"))
                        remaining -= len(part)

                reply = client.execute_interactive(source, allow_stdin=False, stop_on_error=True,
                                                   timeout=40, output_hook=receive)
                status = reply["content"]["status"]
                rows.append({"index": index, "status": status, "text": "".join(chunks),
                             "truncated": remaining == 0})
                if status != "ok":
                    outcome = "failed"
                    break
        except Exception as exc:  # noqa: BLE001 - bounded guest result
            outcome = "failed"
            rows.append({"status": "driver_error", "error": type(exc).__name__})
        finally:
            try:
                if client is not None:
                    client.stop_channels()
            finally:
                if manager.has_kernel:
                    manager.shutdown_kernel(now=True)
    (Path(output) / "kernel-results.json").write_text(json.dumps({
        "protocol": "gridagent-kernel-batch-v1", "status": outcome,
        "verification": "unverified_script_output", "cells": rows,
        "scope": "one kernel within one isolated job; no state retained between jobs",
    }, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    return 0 if outcome == "ok" else 1
