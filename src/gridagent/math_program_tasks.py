"""Write-once mathematical-program studies with conservative interruption recovery."""

from pathlib import Path

from .dsr import Study
from .engineering_ir import fingerprint
from .math_program_router import parse_program, reservation_for, solve, verify

PROTOCOL = "mathematical-program-v1"


def start_program(root, spec):
    spec = parse_program(spec)
    study = Study(Path(root) / "studies")
    study.write("manifest", {"protocol": PROTOCOL, "spec": spec.canonical(),
                             "sha256": spec.sha256()})
    return study.id


def resume_program(root, identifier, *, solver=solve):
    study = Study.reopen(Path(root) / "studies", identifier)
    with study.lock():
        frozen = study.read("manifest")
        spec = parse_program(frozen["spec"])
        if frozen.get("protocol") != PROTOCOL or frozen["sha256"] != spec.sha256():
            raise ValueError("Frozen mathematical program changed")
        reservation = reservation_for(spec)
        fresh = not study.exists("reservation-1")
        if fresh:
            if study.exists("result") or study.exists("report"):
                raise ValueError("Mathematical evidence without reservation")
            study.write("reservation-1", reservation)
        elif study.read("reservation-1") != reservation:
            raise ValueError("Mathematical program reservation changed")
        if fresh:
            try:
                result = solver(spec)
            except Exception as exc:  # noqa: BLE001 - preserve the reserved call, never retry blindly
                result = {"route": spec.route(), "status": "solver_exception",
                          "error_type": type(exc).__name__, "values": None, "objective": None}
            study.write("result", result)
        if study.exists("result"):
            result = study.read("result")
            verdict = verify(spec, result)
        else:
            result = {"route": spec.route(), "status": "unknown_reserved_call"}
            verdict = {"primal": {"passed": False, "checks": [], "objective": None},
                       "lp_certificate": None, "optimality_independently_checked": False,
                       "classification": "no_verified_candidate"}
        report = {"study_id": identifier, "protocol": PROTOCOL, "phase": "mathematical_program_finished",
                  "program_sha256": spec.sha256(), "reservation_sha256": fingerprint(reservation),
                  "solver_result_sha256": fingerprint(result), "solver_result": result,
                  "verification": verdict, "verification_sha256": fingerprint(verdict),
                  "reserved_solver_calls": 1, "completed": verdict["primal"]["passed"],
                  "objective_unit": spec.objective.unit}
        if study.exists("report"):
            if study.read("report") != report:
                raise ValueError("Committed mathematical program evidence changed")
        else:
            study.write("report", report)
        return report
