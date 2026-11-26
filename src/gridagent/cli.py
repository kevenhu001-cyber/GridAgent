import argparse
import json
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown

from .agent import build_agent, model_from_env
from .simulator import AndesSimulator
from .store import ResearchStore, recorded_task


def text_content(message):
    if isinstance(message.content, str):
        return message.content
    return "\n".join(block.get("text", "") for block in message.content
                     if isinstance(block, dict) and block.get("type") == "text")


def tool_summary(message):
    try:
        data = json.loads(message.content)
    except (ValueError, TypeError):
        return f"{message.name}: result received"
    if not isinstance(data, dict):
        return f"{message.name}: result received"
    status = data.get("status", "ok")
    result = f"{message.name}: {status}"
    if data.get("run_id"):
        result += f" | run {data['run_id']}"
    if status != "ok":
        result += f" | {data.get('reason', 'unknown error')}"
    return result


def main():
    parser = argparse.ArgumentParser(description="GridAgent offline research assistant")
    parser.add_argument("--ask", help="Run one research task without TUI")
    parser.add_argument("--budget", type=int, default=3, choices=range(31), metavar="0..30")
    parser.add_argument("--workspace", type=Path, default=Path(".gridagent"))
    parser.add_argument("--session", help="Reopen a session using its full ID")
    parser.add_argument("--sessions", action="store_true", help="List local sessions without an API key")
    parser.add_argument("--dmq-reference", action="store_true", help="Run deterministic DMQ reference without API key")
    parser.add_argument("--dmq", action="store_true", help="Run the open Q/V model quality study")
    parser.add_argument("--dsr", type=Path, help="Run a bounded DSR candidate manifest")
    parser.add_argument("--memory", type=Path, help="Use a fixed DSR history snapshot")
    parser.add_argument("--holdout", action="store_true", help="Exclude target fault outcomes from history")
    parser.add_argument("--snapshot-memory", type=Path, help="Export historical fault records")
    parser.add_argument("--studies", action="store_true", help="List saved research studies")
    args = parser.parse_args()
    store = ResearchStore(args.workspace / "research.sqlite3")
    console = Console()
    if args.dmq_reference:
        from .dmq import format_update, study_updates

        for node, value in study_updates(args.workspace, reference=True):
            console.print(format_update(node, value), markup=False)
        return
    if args.snapshot_memory:
        from .dsr import save_memory_snapshot
        n = save_memory_snapshot(args.workspace / "runs", args.snapshot_memory)
        console.print(f"Saved {n} historical records.", markup=False)
        return
    if args.studies:
        from .dsr import list_studies
        for row in list_studies(args.workspace / "studies"):
            console.print(f"{row['id']}  {row['status']}", markup=False)
        return
    if args.sessions:
        for row in store.sessions():
            console.print(f"{row['id']}  {row['title']}  ({row['tasks']} tasks)", markup=False)
        return
    try:
        model = model_from_env()
        simulator = AndesSimulator(args.workspace / "runs")
        if args.dmq:
            from .dmq import format_update, study_updates
            for node, value in study_updates(args.workspace, model):
                console.print(format_update(node, value), markup=False)
            return
        if args.dsr:
            from .dsr import format_update, study_updates
            for node, value in study_updates(args.dsr, args.workspace, model, simulator, args.memory, args.holdout):
                console.print(format_update(node, value), markup=False)
            return
        sid = store.require_session(args.session) if args.session else store.create_session()
        graph = build_agent(model, simulator, budget=args.budget)
    except ValueError as exc:
        parser.error(str(exc))
    if args.ask:
        console.print(f"Session: {sid}", markup=False)
        for event in recorded_task(graph, store, sid, args.ask):
            for node, update in event.items():
                for message in update.get("messages", []):
                    if node == "tools":
                        console.print(tool_summary(message), markup=False)
                    elif text_content(message):
                        console.print(Markdown(text_content(message)))
        return
    from .dmq import study_updates as dmq_updates
    from .dsr import study_updates
    from .tui import GridApp
    GridApp(graph, args.budget, store, sid,
            dsr_runner=lambda path: study_updates(path, args.workspace, model, simulator, args.memory, args.holdout),
            studies_root=args.workspace / "studies",
            dmq_runner=lambda: dmq_updates(args.workspace, model)).run()
