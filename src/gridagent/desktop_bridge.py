"""Local JSON-lines bridge for the native Windows client. No HTTP server."""
import argparse
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np
from langchain_core.messages import HumanMessage, ToolMessage

from .agent import build_agent, model_from_env
from .cli import text_content, tool_summary
from .commands import workspace_command
from .dsr import list_studies
from .simulator import AndesSimulator
from .store import ResearchStore, recorded_task
from .workspace import list_runs, waveform


def chart_series(root, identifier):
    """Return bounded chart data without dropping per-bucket extrema."""
    first = waveform(root, identifier)
    series = []
    for channel in first["channels"]:
        data = first if channel == first["channel"] else waveform(root, identifier, channel)
        t, y = data["time"], data["value"]
        if len(t) > 1200:
            indices = {0, len(t) - 1}
            for block in np.array_split(np.arange(len(t)), 599):
                indices.add(int(block[np.argmin(y[block])]))
                indices.add(int(block[np.argmax(y[block])]))
            idx = sorted(indices)
        else:
            idx = slice(None)
        series.append({"channel": channel, "time": t[idx].tolist(), "value": y[idx].tolist(),
                       "samples": len(t), "minimum": float(y.min()), "maximum": float(y.max())})
    return series


def dispatch(root, request, emit):
    root = Path(root)
    store = ResearchStore(root / "research.sqlite3")
    action = request["action"]

    def refresh():
        emit("sessions", store.sessions())
        emit("studies", list_studies(root / "studies"))
        emit("runs", list_runs(root))

    if action == "refresh":
        refresh()
    elif action == "new":
        emit("session", store.create_session())
        refresh()
    elif action == "history":
        sid = store.require_session(request["session"])
        for msg in store.history(sid):
            if isinstance(msg, HumanMessage):
                emit("user", text_content(msg))
            elif isinstance(msg, ToolMessage):
                emit("tool", tool_summary(msg))
            elif text_content(msg):
                emit("assistant", text_content(msg))
        for task in store.tasks(sid):
            if task["status"] != "completed":
                emit("status", f"Previous task {task['id'][:8]}: {task['status']}")
    elif action == "ask":
        model = model_from_env()
        budget = int(request.get("budget", 3))
        graph = build_agent(model, AndesSimulator(root / "runs"), budget=budget, workspace=root)
        sid = store.require_session(request["session"]) if request.get("session") else store.create_session()
        emit("session", sid)
        prompt = request["prompt"].strip()
        if not prompt:
            raise ValueError("Enter a research question")
        for event in recorded_task(graph, store, sid, prompt):
            for node, update in event.items():
                if "used" in update:
                    emit("status", f"{update['used']}/{budget} simulation attempts")
                for msg in update.get("messages", []):
                    if node == "tools":
                        emit("tool", tool_summary(msg))
                    elif text_content(msg):
                        emit("assistant", text_content(msg))
        refresh()
    elif action == "waveform":
        emit("waveform", chart_series(root, request["run"]))
    elif action == "local":
        for line in workspace_command(root, request["command"], request.get("args", [])):
            emit("result", line)
        refresh()
    elif action == "dmq":
        from .dmq import format_update, study_updates

        reference = bool(request.get("reference", False))
        model = None if reference else model_from_env()
        for node, value in study_updates(root, model, reference=reference):
            emit("result", format_update(node, value))
        refresh()
    elif action == "dsr":
        from .dsr import format_update, study_updates

        model = model_from_env()
        for node, value in study_updates(request["manifest"], root, model, AndesSimulator(root / "runs"),
                                         request.get("memory"), bool(request.get("holdout", False))):
            emit("result", format_update(node, value))
        refresh()
    else:
        raise ValueError("Unknown desktop action")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    # Keep protocol output separate from library logging and never show raw stderr in the UI.
    output = sys.stdout

    def emit(kind, data):
        print(json.dumps({"kind": kind, "data": data}, ensure_ascii=True, allow_nan=False),
              file=output, flush=True)

    try:
        request = json.loads(sys.stdin.readline())
        with redirect_stdout(sys.stderr):
            dispatch(args.workspace, request, emit)
        emit("done", True)
    except Exception as exc:  # noqa: BLE001 - client protocol boundary
        emit("error", type(exc).__name__ + ": desktop operation failed; check configuration and input")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
