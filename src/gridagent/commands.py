"""Shared deterministic commands for CLI and TUI."""
from pathlib import Path

from .simulator import AndesSimulator
from .sweep import SweepRequest, format_update, sweep_updates
from .workspace import list_runs, study_summary, waveform, waveform_text


def workspace_command(root, command, args):
    root = Path(root)
    if command == "optimize" and len(args) <= 1:
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
