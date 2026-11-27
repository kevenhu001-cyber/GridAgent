"""Local JSON-lines bridge for the native Windows client. No HTTP server."""
import argparse
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

from .store import ResearchStore


def chart_series(root, identifier):
    """Return bounded chart data without dropping per-bucket extrema."""
    import numpy as np

    from .workspace import waveform

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

    def tool_event(message, summary):
        emit("tool", summary)
        if request.get("presentation") == 1:
            from .artifact_presentation import artifact_from_tool

            artifact = artifact_from_tool(root, message)
            if artifact is not None:
                emit("artifact", artifact)

    def refresh():
        from .dsr import list_studies
        from .model_revisions import revisions
        from .research import ResearchTasks
        from .workspace import list_runs

        emit("sessions", store.sessions())
        emit("studies", list_studies(root / "studies"))
        emit("runs", list_runs(root))
        emit("research_tasks", ResearchTasks(root).listing())
        emit("model_revisions", revisions(root))

    if action == "initialize":
        from .model_settings import active_settings

        emit("model_settings", active_settings(root).model_dump())
        emit("sessions", store.sessions())
    elif action == "plugins":
        from .plugins import status

        emit("plugins", status())
    elif action in {"model-settings", "model-save", "model-test"}:
        from .model_settings import ModelSettings, check_connection, save_settings, stored_settings

        if action == "model-settings":
            emit("model_settings", stored_settings(root).model_dump())
        elif action == "model-save":
            saved = save_settings(root, request["model"], request.get("base_url", ""))
            emit("model_settings", saved.model_dump())
            emit("result", "Model and endpoint saved. The API key remains in this session.")
        else:
            settings = ModelSettings(model=request["model"], base_url=request.get("base_url", ""))
            try:
                emit("result", check_connection(settings))
            except Exception as exc:  # noqa: BLE001 - keep provider diagnostics and secrets out of the UI
                emit("error", f"Connection failed ({type(exc).__name__}). Check endpoint, model and session key.")
    elif action == "refresh":
        refresh()
    elif action == "new":
        emit("session", store.create_session())
        if request.get("lightweight"):
            emit("sessions", store.sessions())
        else:
            refresh()
    elif action == "history":
        from langchain_core.messages import HumanMessage, ToolMessage

        from .message_format import text_content, tool_summary

        sid = store.require_session(request["session"])
        for msg in store.history(sid):
            if isinstance(msg, HumanMessage):
                emit("user", text_content(msg))
            elif isinstance(msg, ToolMessage):
                tool_event(msg, tool_summary(msg))
            elif text_content(msg):
                emit("assistant", text_content(msg))
        for task in store.tasks(sid):
            if task["status"] != "completed":
                emit("status", f"Previous task {task['id'][:8]}: {task['status']}")
    elif action == "ask":
        from .agent import build_agent, model_from_env
        from .message_format import text_content, tool_summary
        from .simulator import AndesSimulator
        from .store import recorded_task

        model = model_from_env(root)
        budget = int(request.get("budget", 3))
        streaming = request.get("stream", False) is True
        on_delta = (lambda text: emit("assistant_delta", text)) if streaming else None
        sid = store.require_session(request["session"]) if request.get("session") else store.create_session()
        graph = build_agent(model, AndesSimulator(root / "runs"), budget=budget, workspace=root, on_delta=on_delta,
                            session_store=store, session_id=sid)
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
                    elif streaming:
                        # The complete stored message is authoritative; reconcile the preview even if empty.
                        emit("assistant_end", text_content(msg))
                    elif text_content(msg):
                        emit("assistant", text_content(msg))
        refresh()
    elif action == "artifact-preview":
        from .artifact_presentation import preview_run

        emit("artifact_preview", preview_run(root, request["run"]))
    elif action == "waveform":
        emit("waveform", chart_series(root, request["run"]))
    elif action == "analysis-charts":
        from .scientific_charts import chart_data

        emit("analysis_charts", chart_data(root, request["run"]))
    elif action == "waveform-overlay":
        from .scientific_charts import plot, series

        ids = request["runs"]
        if not 2 <= len(ids) <= 4 or len(set(ids)) != len(ids):
            raise ValueError("Select two to four runs with voltage waveforms")
        frames = [{row["channel"]: row for row in chart_series(root, identifier)} for identifier in ids]
        common = [name for name in frames[0] if all(name in frame for frame in frames)]
        if not common:
            raise ValueError("The selected runs have no common waveform channels")
        name = common[0]
        traces = [series(identifier[:8], frame[name]["time"], frame[name]["value"])
                  for identifier, frame in zip(ids, frames, strict=True)]
        emit("analysis_charts", [plot(f"Voltage overlay · {name}", "Time (s)", "Voltage (p.u.)", traces)])
    elif action in {"topology", "save-model-revision", "run-model-revision"}:
        from .model_revisions import create_revision, run_revision, topology

        if action == "topology":
            emit("topology", topology(root, request["run"]))
        elif action == "save-model-revision":
            revision = create_revision(root, request["run"], request["edit"])
            emit("result", f"Saved model revision {revision['id']} · {revision['name']}")
            refresh()
        else:
            result = run_revision(root, request["revision"])
            emit("result", f"Model revision run {result['run_id']} · {result['status']}")
            refresh()
    elif action == "research":
        from .research import format_status, task_command

        command = request["command"]
        for row in task_command(root, command, request.get("args", [])):
            if isinstance(row, dict):
                emit("research_task", {"id": row["id"], "stage": row["stage"], "summary": format_status(row),
                                       "runs_used": row["runs_used"], "max_runs": row["max_runs"]})
            else:
                emit("result", row)
        refresh()
    elif action == "local":
        from .commands import workspace_command

        for line in workspace_command(root, request["command"], request.get("args", [])):
            emit("result", line)
        refresh()
    elif action == "dmq":
        from .agent import model_from_env
        from .dmq import format_update, study_updates

        reference = bool(request.get("reference", False))
        model = None if reference else model_from_env(root)
        for node, value in study_updates(root, model, reference=reference):
            emit("result", format_update(node, value))
        refresh()
    elif action == "dsr":
        from .agent import model_from_env
        from .dsr import format_update, study_updates
        from .simulator import AndesSimulator

        model = model_from_env(root)
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
