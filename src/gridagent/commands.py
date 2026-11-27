"""Shared deterministic commands for CLI and TUI."""
from pathlib import Path

from .simulator import AndesSimulator
from .sweep import SweepRequest, format_update, sweep_updates
from .workspace import list_runs, study_summary, waveform, waveform_text


def workspace_command(root, command, args, *, model_factory=None):
    from .agent import model_from_env

    root = Path(root)
    def create_model(*, settings=None):
        return model_factory(settings=settings) if model_factory else model_from_env(root, settings=settings)

    if command == "research" or command.startswith("research-"):
        from .research import format_status, task_command

        for row in task_command(root, command, args, model_factory=create_model):
            yield format_status(row) if isinstance(row, dict) else row
    elif command in {"dispatch-ir", "dispatch-resume", "dispatch-status", "dispatch-cancel"} and len(args) == 1:
        import json

        from filelock import Timeout

        from .dispatch_ir import DispatchStudy
        from .dispatch_tasks import DispatchTasks

        tasks = DispatchTasks(root)
        try:
            if command == "dispatch-ir":
                with Path(args[0]).open("rb") as handle:
                    payload = handle.read(1024 * 1024 + 1)
                if len(payload) > 1024 * 1024:
                    raise ValueError("Dispatch input exceeds 1 MiB")
                identifier = tasks.start(DispatchStudy.model_validate_json(payload))
                yield "Dispatch task: " + identifier
                result = tasks.resume(identifier)
            elif command == "dispatch-resume":
                result = tasks.resume(args[0])
            elif command == "dispatch-cancel":
                result = tasks.cancel(args[0])
            else:
                result = tasks.summary(args[0])
        except Timeout as exc:
            raise ValueError("Dispatch task is already running") from exc
        yield json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
    elif command in {"ac-collection-plan", "ac-collection-resume", "ac-train",
                     "ac-train-collection", "ac-standard-screening"}:
        from .research_workbench import workbench_command

        yield from workbench_command(root, command, args)
    elif command == "plugins" and not args:
        from .plugins import status

        for row in status():
            versions = ", ".join(f"{name} {version}" for name, version in row["versions"].items())
            yield f"{row['id']} · {row['title']} · {'installed' if row['installed'] else 'not installed'} {versions}"
    elif command in {"plugin-install", "plugin-remove"} and len(args) == 1:
        from .plugins import install, uninstall

        yield f"{command} · {args[0]} · started"
        yield (install if command == "plugin-install" else uninstall)(args[0])
    elif command in {"plugin-check", "plugin-update", "plugin-rollback"} and len(args) == 1:
        from .plugins import install, rollback, updates

        plugin = args[0]
        if command == "plugin-check":
            changes = updates(plugin)
            yield ("\n".join(f"{name} · {row['installed']} → {row['available']}" for name, row in changes.items())
                   if changes else "The plugin is at the currently resolved versions")
        elif command == "plugin-update":
            yield install(plugin, update=True)
        else:
            yield rollback(plugin)
    elif command == "experience" and not args:
        from .experience import list_experience

        rows = list_experience(root)
        if not rows:
            yield "No independently rechecked repair experiences yet."
        for row in rows:
            changes = ", ".join(f"{c['component']}.{c['parameter']} {c['direction']}" for c in row["changes"])
            yield f"{row['backend']} · {row['study_id']} · {', '.join(row['failed_checks'])} · {changes}"
    elif command == "modeling-benchmark" and len(args) == 1:
        from .modeling_benchmark import benchmark_updates, model_candidate

        for row in benchmark_updates(root, args[0], model_candidate(create_model(), args[0])):
            yield row
    elif command == "model-repair" and len(args) == 1:
        from .model_repair import Manifest, model_proposer, repair_updates
        from .model_repair import format_update as format_repair

        source = Path(args[0])
        if source.stat().st_size > 1024 * 1024:
            raise ValueError("Manifest exceeds 1 MiB")
        manifest = Manifest.model_validate_json(source.read_bytes())
        for row in repair_updates(root, manifest, model_proposer(create_model())):
            yield format_repair(row)
    elif command == "drafts" and not args:
        from .script_drafts import list_drafts

        for row in list_drafts(root):
            yield f"{row['title']} · {row['id']} · {row['status']}"
    elif command == "register-ngspice" and len(args) == 1:
        import subprocess

        from .external_runtime import register_ngspice

        try:
            info = register_ngspice(root, args[0])
        except subprocess.SubprocessError as exc:
            raise ValueError("ngspice version probe failed") from exc
        yield f"Registered ngspice {info['version']}"
    elif command == "ngspice-rc" and len(args) == 3:
        import json

        from .external_runtime import run_rc

        summary = run_rc(root, {"analysis": args[0], "resistance_ohm": args[1], "capacitance_f": args[2]})
        yield json.dumps(summary, ensure_ascii=False)
    elif command == "andes-batch" and len(args) == 1:
        from .andes_batch import AndesBatch, run_batch

        source = Path(args[0])
        if source.stat().st_size > 1024 * 1024:
            raise ValueError("ANDES batch exceeds 1 MiB")
        yield from run_batch(root, AndesBatch.model_validate_json(source.read_bytes()))
    elif command == "backends" and not args:
        from .native_backends import available_backends

        for row in available_backends(root):
            details = row["version"] or ("available" if row["installed"] else "unavailable")
            yield f"{row['name']} · {details} · {row['capabilities']}"
    elif command == "native-program" and len(args) == 1:
        import json

        from .native_backends import ADAPTER, run_program

        source = Path(args[0])
        if source.stat().st_size > 1024 * 1024:
            raise ValueError("Program file exceeds 1 MiB")
        program = ADAPTER.validate_json(source.read_bytes())
        result = run_program(root, program)
        yield json.dumps(result, ensure_ascii=False, indent=2)
    elif command == "native-table" and len(args) in (2, 3, 4):
        import json

        from .native_results import read_table

        yield json.dumps(read_table(root, args[0], args[1], int(args[2]) if len(args)>2 else 0,
                                    int(args[3]) if len(args)>3 else 20), ensure_ascii=False, indent=2)
    elif command == "import-knowledge" and len(args) == 1:
        from .knowledge_store import import_pack

        identifier, count = import_pack(root, args[0])
        yield f"Registered reference pack {identifier} ({count} entries)"
    elif command == "knowledge" and not args:
        from .knowledge_store import list_packs

        for row in list_packs(root):
            yield f"{row['title']} · {row['entries']} entries · {row['id']}"
    elif command == "models" and not args:
        from .models import list_models

        for row in list_models(root):
            yield f"{row['name']} · {row['id']} · {row['format']}"
    elif command == "import-model" and len(args) == 1:
        from .models import register_model

        identifier = register_model(root, args[0])
        yield f"Registered model {identifier}. Use inspect_case to validate it before simulation."
    elif command == "paper-trials" and 2 <= len(args) <= 3:
        from .paper_trials import configured_trials

        yield from configured_trials(root, args[0], int(args[1]), args[2] if len(args) == 3 else None,
                                     model_factory=create_model)
    elif command == "paper-kpi" and len(args) == 2:
        import json

        from .paper import original_kpis

        yield json.dumps(original_kpis(args[0], float(args[1])), indent=2, ensure_ascii=False)
    elif command == "paper-edit" and len(args) == 4:
        from .paper import edit_original_model

        identifier, report = edit_original_model(root, dict(zip(("Kqp", "Kqi", "Kvp", "Kvi"), map(float, args))))
        yield f"Original WECC model edit verified · {identifier} · {report['new']} · not simulated"
    elif command == "paper-dmq" and len(args) == 1:
        from .paper_dmq import model_proposer, original_dmq, profile_runner

        yield from original_dmq(root, model_proposer(create_model()), profile_runner(args[0]))
    elif command == "paper-dsr" and len(args) == 1:
        from .paper import model_estimator, paper_rank
        from .paper_dsr import profile_runner

        yield from paper_rank(root, model_estimator(create_model()), profile_runner(args[0]))
    elif command == "paper-mitigate" and len(args) == 1:
        from .paper import model_estimator, paper_rank
        from .paper_dsr import mitigation_runner
        from .paper_mitigation import model_proposer

        runner, budget = mitigation_runner(args[0])
        model = create_model()
        yield from paper_rank(root, model_estimator(model), runner, model_proposer(model), budget)
    elif command == "paper-rank" and not args:
        from .paper import model_estimator, paper_rank

        yield from paper_rank(root, model_estimator(create_model()))
    elif command in {"remember-ac-repair", "search-ac-experience"} and len(args) == 1:
        import json

        from filelock import Timeout

        from .ac_repair_experience import remember_ac_repair, search_ac_experience

        try:
            report = (remember_ac_repair(root, args[0]) if command == "remember-ac-repair"
                      else search_ac_experience(root, args[0], physical=True))
        except Timeout as exc:
            raise ValueError("Source evidence is currently locked") from exc
        yield json.dumps(report, ensure_ascii=False, allow_nan=False)
    elif command in {"ac-evidence-repair", "ac-evidence-repair-resume"} and len(args) == 1:
        import json

        from filelock import Timeout

        from .ac_evidence_repair import resume_repair, start_repair
        from .ac_repair_ir import ACRepairAuthorization

        try:
            if command == "ac-evidence-repair":
                with Path(args[0]).open("rb") as handle:
                    payload = handle.read(1024 * 1024 + 1)
                if len(payload) > 1024 * 1024:
                    raise ValueError("AC repair input exceeds 1 MiB")
                identifier = start_repair(root, ACRepairAuthorization.model_validate_json(payload))
                yield "AC evidence repair study: " + identifier
            else:
                identifier = args[0]
            report = resume_repair(root, identifier)
        except Timeout as exc:
            raise ValueError("AC repair or source study is locked") from exc
        yield json.dumps(report, ensure_ascii=False, allow_nan=False)
    elif command in {"adaptive-ac-experiment", "adaptive-ac-experiment-resume"} and len(args) == 1:
        import json

        from filelock import Timeout

        from .adaptive_ac_experiment import resume_adaptive, start_adaptive
        from .adaptive_ac_ir import AdaptiveACExperiment

        try:
            if command == "adaptive-ac-experiment":
                with Path(args[0]).open("rb") as handle:
                    payload = handle.read(1024 * 1024 + 1)
                if len(payload) > 1024 * 1024:
                    raise ValueError("Adaptive AC input exceeds 1 MiB")
                identifier = start_adaptive(root, AdaptiveACExperiment.model_validate_json(payload))
                yield "Adaptive AC experiment study: " + identifier
            else:
                identifier = args[0]
            report = resume_adaptive(root, identifier)
        except Timeout as exc:
            raise ValueError("Adaptive AC experiment or source study is locked") from exc
        yield json.dumps(report, ensure_ascii=False, allow_nan=False)
    elif command in {"ac-diagnostic-experiment", "ac-diagnostic-experiment-resume"} and len(args) == 1:
        import json

        from filelock import Timeout

        from .ac_diagnostic_experiment import resume_experiment, start_experiment
        from .ac_diagnostic_ir import ACDiagnosticExperiment

        try:
            if command == "ac-diagnostic-experiment":
                with Path(args[0]).open("rb") as handle:
                    payload = handle.read(1024 * 1024 + 1)
                if len(payload) > 1024 * 1024:
                    raise ValueError("AC diagnostic input exceeds 1 MiB")
                identifier = start_experiment(root, ACDiagnosticExperiment.model_validate_json(payload))
                yield "AC diagnostic experiment study: " + identifier
            else:
                identifier = args[0]
            report = resume_experiment(root, identifier)
        except Timeout as exc:
            raise ValueError("AC diagnostic experiment or source study is locked") from exc
        yield json.dumps(report, ensure_ascii=False, allow_nan=False)
    elif command in {"diagnostic-experiment", "diagnostic-experiment-resume"} and len(args) == 1:
        import json

        from filelock import Timeout

        from .diagnostic_experiment import resume_experiment, start_experiment
        from .diagnostic_experiment_ir import DiagnosticExperiment

        try:
            if command == "diagnostic-experiment":
                with Path(args[0]).open("rb") as handle:
                    payload = handle.read(1024 * 1024 + 1)
                if len(payload) > 1024 * 1024:
                    raise ValueError("Diagnostic experiment input exceeds 1 MiB")
                identifier = start_experiment(root, DiagnosticExperiment.model_validate_json(payload))
                yield "Diagnostic experiment study: " + identifier
            else:
                identifier = args[0]
            report = resume_experiment(root, identifier)
        except Timeout as exc:
            raise ValueError("Diagnostic experiment or source study is locked") from exc
        yield json.dumps(report, ensure_ascii=False, allow_nan=False)
    elif command == "diagnose-study" and len(args) == 1:
        import json

        from filelock import Timeout

        from .diagnosis import diagnose_study

        try:
            report = diagnose_study(root, args[0])
        except Timeout as exc:
            raise ValueError("Source study is currently locked") from exc
        yield json.dumps(report, ensure_ascii=False, allow_nan=False)
    elif command in {"ac-check", "ac-check-resume"} and len(args) == 1:
        import json

        from filelock import Timeout

        from .ac_check import resume_ac_check, start_ac_check
        from .ac_check_ir import ACCheckSpec

        try:
            if command == "ac-check":
                with Path(args[0]).open("rb") as handle:
                    payload = handle.read(1024 * 1024 + 1)
                if len(payload) > 1024 * 1024:
                    raise ValueError("AC cross-check input exceeds 1 MiB")
                identifier = start_ac_check(root, ACCheckSpec.model_validate_json(payload))
                yield "AC cross-check study: " + identifier
            else:
                identifier = args[0]
            report = resume_ac_check(root, identifier)
        except Timeout as exc:
            raise ValueError("AC cross-check or source study is already running") from exc
        yield json.dumps(report, ensure_ascii=False, allow_nan=False)
    elif command in {"math-program", "math-resume"} and len(args) == 1:
        import json

        from filelock import Timeout

        from .math_program_router import parse_program
        from .math_program_tasks import resume_program, start_program

        if command == "math-program":
            with Path(args[0]).open("rb") as handle:
                payload = handle.read(1024 * 1024 + 1)
            if len(payload) > 1024 * 1024:
                raise ValueError("Mathematical program exceeds 1 MiB")
            identifier = start_program(root, parse_program(json.loads(payload)))
            yield "Mathematical program study: " + identifier
        else:
            identifier = args[0]
        try:
            report = resume_program(root, identifier)
        except Timeout as exc:
            raise ValueError("Mathematical program is already running") from exc
        yield json.dumps(report, ensure_ascii=False, allow_nan=False)
    elif command in {"optimize-ir", "optimize-resume"} and len(args) == 1:
        import json

        from filelock import Timeout

        from .engineering_optimization import resume_optimization, start_optimization
        from .optimization_ir import ACOptimizationSpec

        if command == "optimize-ir":
            with Path(args[0]).open("rb") as handle:
                payload = handle.read(1024 * 1024 + 1)
            if len(payload) > 1024 * 1024:
                raise ValueError("Optimization input exceeds 1 MiB")
            identifier = start_optimization(root, ACOptimizationSpec.model_validate_json(payload))
            yield "Optimization study: " + identifier
        else:
            identifier = args[0]
        try:
            for row in resume_optimization(root, identifier):
                yield json.dumps(row, ensure_ascii=False, allow_nan=False)
        except Timeout as exc:
            raise ValueError("Optimization study or child is already running") from exc
    elif command == "optimize" and len(args) <= 1:
        from .optimization import format_update as format_optimization
        from .optimization import optimize_updates

        for node, data in optimize_updates(root / "studies", int(args[0]) if args else 24):
            yield format_optimization(node, data)
    elif command == "resume-dsr" and len(args) == 1:
        from filelock import Timeout

        from .dsr import format_update as format_dsr
        from .dsr import resume_dsr

        try:
            for node, data in resume_dsr(root / "studies", args[0], AndesSimulator(root / "runs")):
                yield format_dsr(node, data)
        except Timeout as exc:
            raise ValueError("Study is currently executing in another process") from exc
    elif command == "runs" and not args:
        for row in list_runs(root):
            yield f"{row['id']}  {row['operation']}  {row['status']}"
    elif command == "study" and len(args) == 1:
        yield study_summary(root, args[0])
    elif command == "wave" and 1 <= len(args) <= 2:
        yield waveform_text(waveform(root, args[0], args[1] if len(args) == 2 else None))
    elif command == "study-wave" and 2 <= len(args) <= 3:
        yield waveform_text(waveform(root, args[0], args[2] if len(args) == 3 else None, args[1]))
    elif command == "eigen" and not args:
        result = AndesSimulator(root / "runs").run("eigen", {"case": "kundur"})
        yield f"Eigenanalysis · {result.get('status')} · run {result.get('run_id', '-')}"
        if result.get("status") != "ok":
            yield result.get("reason", "No numerical result")
            return
        metrics = result["metrics"]
        yield (f"{metrics['mode_count']} modes · {metrics['growing_count']} growing · "
               f"{metrics['neutral_count']} neutral · {metrics['decaying_count']} decaying")
        for row in metrics["least_damped_oscillatory_modes"]:
            yield f"{row['frequency_hz']:.4g} Hz · damping {row['damping_ratio']:.3%}"
    elif command == "sweep" and len(args) >= 2:
        bus = float(args[0])
        if not bus.is_integer():
            raise ValueError("Bus must be an integer")
        spec = SweepRequest(bus=int(bus), durations_s=[float(x) for x in args[1:]])
        for node, data in sweep_updates(spec, AndesSimulator(root / "runs"), root / "studies"):
            yield format_update(node, data)
    else:
        raise ValueError("Invalid command arguments; see /help")
