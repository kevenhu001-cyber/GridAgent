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
    if message.name == "research_plan" and status == "ok":
        return "Research plan: " + data["objective"] + "\n" + "\n".join(f"{i+1}. {step}" for i, step in enumerate(data["steps"])) + "\nVerify: " + data["verification"]
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
    parser.add_argument("--offline", action="store_true", help="Open local research TUI without an API key")
    parser.add_argument("--optimize", type=int, metavar="BUDGET", help="Optimize surrogate PI gains offline")
    parser.add_argument("--resume-dsr", help="Resume a frozen DSR study without an API key")
    parser.add_argument("--eigen", action="store_true", help="Run ANDES small-signal analysis")
    parser.add_argument("--sweep", nargs="+", type=float, metavar="BUS_OR_DURATION",
                        help="Sweep fault duration: BUS DURATION [DURATION ...]")
    parser.add_argument("--runs", action="store_true", help="List local numerical runs")
    parser.add_argument("--study", help="View a saved study")
    parser.add_argument("--wave", nargs="+", metavar="ID_OR_CHANNEL", help="View a saved run waveform")
    parser.add_argument("--study-wave", nargs="+", metavar="ID_PATH_CHANNEL", help="View a study waveform")
    parser.add_argument("--paper-dmq", metavar="PROFILE", help="Run original licensed DMQ")
    parser.add_argument("--import-knowledge", type=Path, metavar="JSON")
    parser.add_argument("--knowledge", action="store_true")
    parser.add_argument("--import-model", type=Path, metavar="XLSX")
    parser.add_argument("--models", action="store_true")
    parser.add_argument("--paper-trials", nargs="+", metavar="TASK_COUNT_PROFILE", help="Independent paper trials")
    parser.add_argument("--paper-mitigate", metavar="PROFILE", help="Screen and test fresh condenser variants")
    parser.add_argument("--paper-dsr", metavar="PROFILE", help="Run original licensed top-three DSR")
    parser.add_argument("--paper-rank", action="store_true", help="Predict original paper DSR ranking")
    parser.add_argument("--paper-kpi", nargs=2, metavar=("CSV", "CLEARING_S"))
    parser.add_argument("--paper-edit", nargs=4, metavar="GAIN")
    args = parser.parse_args()
    store = ResearchStore(args.workspace / "research.sqlite3")
    console = Console()
    local_commands = [
        ("import-knowledge", [str(args.import_knowledge)] if args.import_knowledge else None),
        ("knowledge", [] if args.knowledge else None),
        ("import-model", [str(args.import_model)] if args.import_model else None),
        ("models", [] if args.models else None),
        ("paper-trials", args.paper_trials),
        ("paper-mitigate", [args.paper_mitigate] if args.paper_mitigate else None),
        ("paper-dsr", [args.paper_dsr] if args.paper_dsr else None),
        ("paper-dmq", [args.paper_dmq] if args.paper_dmq else None),
        ("paper-rank", [] if args.paper_rank else None),
        ("paper-kpi", args.paper_kpi), ("paper-edit", args.paper_edit),
        ("optimize", [str(args.optimize)] if args.optimize is not None else None),
        ("resume-dsr", [args.resume_dsr] if args.resume_dsr else None),
        ("eigen", [] if args.eigen else None),
        ("sweep", [str(x) for x in args.sweep] if args.sweep else None),
        ("runs", [] if args.runs else None),
        ("study", [args.study] if args.study else None),
        ("wave", args.wave), ("study-wave", args.study_wave),
    ]
    selected = [(name, values) for name, values in local_commands if values is not None]
    if selected:
        from .commands import workspace_command

        if len(selected) != 1:
            parser.error("Select one local research command at a time")
        command, values = selected[0]
        try:
            for line in workspace_command(args.workspace, command, values):
                console.print(line, markup=False)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            parser.error(str(exc))
        return
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
    if args.offline:
        if args.ask or args.dmq or args.dsr:
            parser.error("Offline TUI cannot run model-dependent tasks")
        from .tui import GridApp

        try:
            sid = store.require_session(args.session) if args.session else store.create_session()
        except ValueError as exc:
            parser.error(str(exc))
        GridApp(None, args.budget, store, sid, studies_root=args.workspace / "studies",
                workspace=args.workspace).run()
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
        graph = build_agent(model, simulator, budget=args.budget, workspace=args.workspace)
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
            dmq_runner=lambda: dmq_updates(args.workspace, model), workspace=args.workspace).run()
