import argparse
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown

from .agent import build_agent, model_from_env
from .message_format import text_content, tool_summary
from .simulator import AndesSimulator
from .store import ResearchStore, recorded_task


def main():
    parser = argparse.ArgumentParser(description="GridAgent offline research assistant")
    parser.add_argument("--ask", help="Run one research task without TUI")
    research = parser.add_mutually_exclusive_group()
    research.add_argument("--research", metavar="QUESTION", help="Start a verified AC power-flow research task")
    research.add_argument("--research-manifest", metavar="JSON", help="Start from an authorized research manifest")
    research.add_argument("--research-ir", metavar="JSON", help="Compile and run a versioned AC engineering study")
    research.add_argument("--dispatch-ir", metavar="JSON", help="Compile and run an hourly storage dispatch study")
    research.add_argument("--dispatch-resume", metavar="ID")
    research.add_argument("--dispatch-status", metavar="ID")
    research.add_argument("--dispatch-cancel", metavar="ID")
    research.add_argument("--optimize-ir", metavar="JSON", help="Run authorized AC mixed-variable optimization")
    research.add_argument("--optimize-resume", metavar="ID", help="Resume an AC optimization study")
    research.add_argument("--math-program", metavar="JSON", help="Solve typed LP, MILP, polynomial NLP or unit commitment")
    research.add_argument("--math-resume", metavar="ID", help="Recover a mathematical program study")
    research.add_argument("--ac-check", metavar="JSON", help="Cross-check verified DC commitment with AC snapshots")
    research.add_argument("--ac-check-resume", metavar="ID", help="Recover AC cross-check evidence")
    research.add_argument("--diagnose-study", metavar="ID", help="Diagnose committed study evidence without solving")
    research.add_argument("--diagnostic-experiment", metavar="JSON", help="Run explicitly authorized contingency probes")
    research.add_argument("--diagnostic-experiment-resume", metavar="ID", help="Recover diagnostic experiment evidence")
    research.add_argument("--ac-diagnostic-experiment", metavar="JSON", help="Run authorized single-factor AC probes")
    research.add_argument("--ac-diagnostic-experiment-resume", metavar="ID", help="Recover AC diagnostic evidence")
    research.add_argument("--adaptive-ac-experiment", metavar="JSON", help="Run bounded adaptive AC probe selection")
    research.add_argument("--adaptive-ac-experiment-resume", metavar="ID", help="Recover adaptive AC experiments")
    research.add_argument("--ac-evidence-repair", metavar="JSON", help="Revalidate authorized AC repair candidates")
    research.add_argument("--ac-evidence-repair-resume", metavar="ID", help="Recover AC repair evidence")
    research.add_argument("--remember-ac-repair", metavar="ID", help="Index replay-verified local repair experience")
    research.add_argument("--search-ac-experience", metavar="ID", help="Find historical AC repairs for a source study")
    research.add_argument("--research-tasks", action="store_true", help="List saved research tasks")
    research.add_argument("--research-status", metavar="ID")
    research.add_argument("--research-resume", metavar="ID")
    research.add_argument("--research-cancel", metavar="ID")
    research.add_argument("--research-approve", metavar="ID", help="Approve the listed repair ranges")
    research.add_argument("--research-clarify", nargs=2, metavar=("ID", "ANSWER"))
    research.add_argument("--research-report", nargs=2, metavar=("ID", "NEW_JSON"))
    research.add_argument("--research-benchmark", nargs="*", metavar="TASK_OR_MODE",
                          help="List public AC benchmarks or run TASK [reference|single|multi]")
    research.add_argument("--research-python", metavar="MANIFEST", help="Run verified sandbox Python research")
    research.add_argument("--research-sandbox", choices=("enable", "disable", "status"))
    research.add_argument("--research-compare", nargs="+", metavar="ARG",
                          help="TASK REPEATS MODEL MODEL [MODEL ...] [memory TRAINING_JSON]")
    research.add_argument("--research-experience", nargs="?", const="", metavar="NEW_JSON",
                          help="List verified repairs or export a training-only snapshot")
    parser.add_argument("--research-mode", choices=("single", "multi"), default="single")
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
    parser.add_argument("--modeling-benchmark", choices=["two-bus", "storage-dispatch", "source-short-circuit", "lossy-storage", "lossy-link"])
    parser.add_argument("--experience", action="store_true", help="List verified local repair experiences")
    parser.add_argument("--model-repair", type=Path, metavar="MANIFEST")
    parser.add_argument("--drafts", action="store_true", help="List Python drafts awaiting review")
    parser.add_argument("--plugins", action="store_true")
    parser.add_argument("--plugin-install", metavar="ID")
    parser.add_argument("--plugin-remove", metavar="ID")
    parser.add_argument("--plugin-check", metavar="ID")
    parser.add_argument("--plugin-update", metavar="ID")
    parser.add_argument("--plugin-rollback", metavar="ID")
    parser.add_argument("--backends", action="store_true")
    parser.add_argument("--register-ngspice", metavar="EXE")
    parser.add_argument("--ngspice-rc", nargs=3, metavar=("ANALYSIS", "OHMS", "FARADS"))
    parser.add_argument("--andes-batch", metavar="JSON")
    parser.add_argument("--native-program", type=Path, metavar="JSON")
    parser.add_argument("--native-table", nargs="+", metavar="RUN_TABLE_PAGE")
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
        ("research-multi" if args.research_mode == "multi" else "research",
         [args.research] if args.research is not None else None),
        ("research-manifest", [args.research_manifest] if args.research_manifest else None),
        ("research-ir", [args.research_ir] if args.research_ir else None),
        ("dispatch-ir", [args.dispatch_ir] if args.dispatch_ir else None),
        ("dispatch-resume", [args.dispatch_resume] if args.dispatch_resume else None),
        ("dispatch-status", [args.dispatch_status] if args.dispatch_status else None),
        ("dispatch-cancel", [args.dispatch_cancel] if args.dispatch_cancel else None),
        ("optimize-ir", [args.optimize_ir] if args.optimize_ir else None),
        ("optimize-resume", [args.optimize_resume] if args.optimize_resume else None),
        ("math-program", [args.math_program] if args.math_program else None),
        ("math-resume", [args.math_resume] if args.math_resume else None),
        ("ac-check", [args.ac_check] if args.ac_check else None),
        ("ac-check-resume", [args.ac_check_resume] if args.ac_check_resume else None),
        ("diagnose-study", [args.diagnose_study] if args.diagnose_study else None),
        ("diagnostic-experiment", [args.diagnostic_experiment] if args.diagnostic_experiment else None),
        ("diagnostic-experiment-resume", [args.diagnostic_experiment_resume] if args.diagnostic_experiment_resume else None),
        ("remember-ac-repair", [args.remember_ac_repair] if args.remember_ac_repair else None),
        ("search-ac-experience", [args.search_ac_experience] if args.search_ac_experience else None),
        ("ac-evidence-repair", [args.ac_evidence_repair] if args.ac_evidence_repair else None),
        ("ac-evidence-repair-resume", [args.ac_evidence_repair_resume] if args.ac_evidence_repair_resume else None),
        ("adaptive-ac-experiment", [args.adaptive_ac_experiment] if args.adaptive_ac_experiment else None),
        ("adaptive-ac-experiment-resume",
         [args.adaptive_ac_experiment_resume] if args.adaptive_ac_experiment_resume else None),
        ("ac-diagnostic-experiment", [args.ac_diagnostic_experiment] if args.ac_diagnostic_experiment else None),
        ("ac-diagnostic-experiment-resume",
         [args.ac_diagnostic_experiment_resume] if args.ac_diagnostic_experiment_resume else None),
        ("research-tasks", [] if args.research_tasks else None),
        ("research-status", [args.research_status] if args.research_status else None),
        ("research-resume", [args.research_resume] if args.research_resume else None),
        ("research-cancel", [args.research_cancel] if args.research_cancel else None),
        ("research-approve", [args.research_approve] if args.research_approve else None),
        ("research-clarify", args.research_clarify), ("research-report", args.research_report),
        ("research-benchmark", args.research_benchmark),
        ("research-python", [args.research_python] if args.research_python else None),
        ("research-sandbox", [args.research_sandbox] if args.research_sandbox else None),
        ("research-compare", args.research_compare),
        ("research-experience", [args.research_experience] if args.research_experience else
         [] if args.research_experience is not None else None),
        ("plugins", [] if args.plugins else None),
        ("plugin-install", [args.plugin_install] if args.plugin_install else None),
        ("plugin-remove", [args.plugin_remove] if args.plugin_remove else None),
        ("plugin-check", [args.plugin_check] if args.plugin_check else None),
        ("plugin-update", [args.plugin_update] if args.plugin_update else None),
        ("plugin-rollback", [args.plugin_rollback] if args.plugin_rollback else None),
        ("experience", [] if args.experience else None),
        ("modeling-benchmark", [args.modeling_benchmark] if args.modeling_benchmark else None),
        ("model-repair", [str(args.model_repair)] if args.model_repair else None),
        ("drafts", [] if args.drafts else None),
        ("backends", [] if args.backends else None),
        ("register-ngspice", [args.register_ngspice] if args.register_ngspice else None),
        ("ngspice-rc", args.ngspice_rc),
        ("andes-batch", [args.andes_batch] if args.andes_batch else None),
        ("native-program", [str(args.native_program)] if args.native_program else None),
        ("native-table", args.native_table),
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
        model = model_from_env(args.workspace)
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
        if args.ask or args.dmq or args.dsr:
            parser.error(str(exc))
        from .tui import GridApp

        try:
            sid = store.require_session(args.session) if args.session else store.create_session()
        except ValueError as session_error:
            parser.error(str(session_error))
        GridApp(None, args.budget, store, sid, studies_root=args.workspace / "studies",
                workspace=args.workspace).run()
        return
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
