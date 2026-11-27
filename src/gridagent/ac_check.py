"""Independent AC snapshot evidence and durable cross-check of a completed UC study."""

import math
from pathlib import Path
from uuid import uuid4

from .ac_check_ir import ACCheckSpec, snapshot_study, validate_mapping
from .dsr import Study
from .engineering_compiler import compile_study
from .engineering_ir import fingerprint
from .evidence import artifact_digest, capture_evidence
from .execution_plan import ac_plan
from .math_program_tasks import resume_program
from .model_quality import table
from .native_backends import run_program
from .research import evaluate_candidate, recover_run
from .workspace import artifact_folder

PROTOCOL = "dc-ac-cross-check-v1"
EXTRA = ("res_ext_grid.csv", "res_gen.csv", "res_load.csv", "res_storage.csv")


def load_commitment(root, spec):
    source = Study.reopen(root / "studies", spec.commitment_study_id)
    if not all(source.exists(name) for name in ("manifest", "reservation-1", "result", "report")):
        raise ValueError("AC cross-check requires a completed commitment study")
    frozen = source.read("manifest")
    commitment = validate_mapping(spec, frozen["spec"])
    report = resume_program(root, spec.commitment_study_id)
    if not report["completed"] or report["program_sha256"] != commitment.sha256():
        raise ValueError("DC commitment must pass independent verification")
    physical = report["verification"]["commitment"]["physical"]
    if not physical or not physical["passed"]:
        raise ValueError("Missing verified DC physical schedule")
    return commitment, physical["schedule"], fingerprint(report)


def prepare(root, spec):
    commitment, schedule, report_sha = load_commitment(root, spec)
    cases = []
    for snapshot in spec.snapshots:
        source, expected = snapshot_study(spec, commitment, schedule, snapshot)
        compiled = compile_study(source)
        plan = ac_plan(compiled.manifest, compiled.provenance)
        program = compiled.manifest.program.model_dump(mode="json")
        request = compiled.manifest.scenarios[0].materialize(program)
        cases.append((snapshot, source, expected, compiled, plan, request))
    return commitment, cases, report_sha


def start_ac_check(root, spec):
    root = Path(root).resolve()
    spec = ACCheckSpec.model_validate(spec)
    _, cases, report_sha = prepare(root, spec)
    study = Study(root / "studies")
    study.write("manifest", {"protocol": PROTOCOL, "spec": spec.canonical(), "sha256": spec.sha256(),
                             "dc_report_sha256": report_sha,
                             "requests": [fingerprint(case[-1]) for case in cases]})
    return study.id


def extra_checks(spec, commitment, source, expected, compiled, folder, snapshot):
    checks, unit_results = [], {}
    tolerance = spec.dispatch_tolerance_mw
    indices = compiled.provenance["device_indices"]

    def check(name, value, limit):
        value = float(value)
        checks.append({"id": name, "passed": math.isfinite(value) and value <= limit,
                       "violation": max(0.0, value) if math.isfinite(value) else None, "tolerance": limit})

    def read_device(device, p, q=None):
        entry = indices[device]
        row = table(folder, "res_" + entry["table"]).loc[entry["index"]]
        actual_p, actual_q = float(row.p_mw), float(row.q_mvar)
        if not math.isfinite(actual_p) or not math.isfinite(actual_q):
            raise ValueError("Non-finite AC device output")
        check("p:"+device, abs(actual_p-p), tolerance)
        if q is not None:
            check("q:"+device, abs(actual_q-q), tolerance)
        return actual_p, actual_q

    generation = 0.0
    for unit in commitment.units:
        if unit.id not in expected:
            continue
        target = expected[unit.id]
        entry = indices[target["device"]]
        row = table(folder, "res_" + entry["table"]).loc[entry["index"]]
        p, q = float(row.p_mw), float(row.q_mvar)
        if not math.isfinite(p) or not math.isfinite(q):
            raise ValueError("Non-finite AC unit output")
        check("capacity:"+unit.id, max(unit.minimum_mw-p, p-unit.maximum_mw), tolerance)
        limits = spec.unit_reactive_limits[unit.id]
        check("reactive:"+unit.id, max(limits.minimum_mvar-q, q-limits.maximum_mvar), tolerance)
        limit = spec.slack_max_deviation_mw if unit.id == spec.slack_unit else tolerance
        check("dispatch:"+unit.id, abs(p-target["p_mw"]), limit)
        if snapshot.outage_line:
            check("outage-up:"+unit.id, p-target["base_mw"]-target["reserve_mw"], tolerance)
            down = unit.ramp_down_mw*commitment.network.reserve_response_minutes/60
            check("outage-down:"+unit.id, target["base_mw"]-p-down, tolerance)
        unit_results[unit.id] = {"scheduled_mw": target["p_mw"], "actual_mw": p,
                                 "deviation_mw": p-target["p_mw"], "reactive_mvar": q}
        generation += p
    demand = 0.0
    for device in source.model.devices:
        if device.kind == "load":
            p, _ = read_device(device.id, device.active_mw, device.reactive_mvar)
            demand += p
        elif device.kind == "storage":
            p, _ = read_device(device.id, device.charging_mw, device.reactive_mvar)
            demand += p
    losses = 0.0
    line_results = {}
    lines = table(folder, "res_line")
    for line in commitment.network.lines:
        idx = indices[line.id]["index"]
        row = lines.loc[idx]
        if line.id == snapshot.outage_line:
            # Pandapower may use NaN or zero for an outaged branch. The existing
            # native evidence covers the in-service flag; explicitly check it here.
            check("outage:"+line.id, int(bool(table(folder, "line").at[idx, "in_service"])), 0)
            continue
        a, b = float(row.p_from_mw), float(row.p_to_mw)
        if not math.isfinite(a) or not math.isfinite(b):
            raise ValueError("Non-finite AC line flow")
        loss = a+b
        check("passive-loss:"+line.id, -loss, tolerance)
        check("active-limit:"+line.id, max(abs(a), abs(b))-line.limit_mw, tolerance)
        losses += loss
        line_results[line.id] = {"from_mw": a, "to_mw": b, "loss_mw": loss}
    check("loss-reconciliation", abs(generation-demand-losses), spec.acceptance.balance_tolerance_mva)
    return {"passed": all(c["passed"] for c in checks), "checks": checks, "units": unit_results,
            "lines": line_results, "network_loss_mw": losses,
            "slack_deviation_mw": unit_results[spec.slack_unit]["deviation_mw"]}


def observe(root, spec, commitment, case, reservation):
    snapshot, source, expected, compiled, plan, request = case
    native = recover_run(root, reservation)
    verdict = evaluate_candidate(root, native, request, compiled.manifest,
                                 compiled.manifest.program.model_dump(mode="json"))
    evidence = capture_evidence(root, plan, "snapshot", reservation["run_id"], request,
                                version=native.get("version"), verdict=verdict)
    supplement, physical = [], None
    if evidence.status == "verified":
        try:
            folder = artifact_folder(root, "runs", reservation["run_id"])
            supplement = [artifact_digest(folder, name).model_dump(mode="json") for name in EXTRA]
            physical = extra_checks(spec, commitment, source, expected, compiled, folder, snapshot)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            physical = {"passed": False, "reason": type(exc).__name__}
    return {"snapshot": snapshot.model_dump(mode="json"), "run_id": reservation["run_id"],
            "ac_model_sha256": source.model.sha256(), "native_evidence": evidence.model_dump(mode="json"),
            "native_verdict": verdict, "supplementary_artifacts": supplement, "physical": physical,
            "passed": evidence.status == "verified" and physical is not None and physical["passed"]}


def resume_ac_check(root, identifier, *, solver=run_program):
    root = Path(root).resolve()
    study = Study.reopen(root / "studies", identifier)
    with study.lock():
        frozen = study.read("manifest")
        spec = ACCheckSpec.model_validate(frozen["spec"])
        if frozen.get("protocol") != PROTOCOL or frozen["sha256"] != spec.sha256():
            raise ValueError("Frozen AC cross-check input changed")
        commitment, cases, report_sha = prepare(root, spec)
        if report_sha != frozen["dc_report_sha256"] or frozen["requests"] != [
                fingerprint(case[-1]) for case in cases]:
            raise ValueError("Frozen DC schedule or AC requests changed")
        observed = []
        for index, case in enumerate(cases, 1):
            name, output = f"reservation-{index}", f"evaluation-{index}"
            request_hash = fingerprint(case[-1])
            fresh = not study.exists(name)
            if fresh:
                if study.exists(output) or study.exists("report"):
                    raise ValueError("AC evidence without reservation")
                study.write(name, {"run_id": uuid4().hex, "request_sha256": request_hash})
            reservation = study.read(name)
            if reservation["request_sha256"] != request_hash:
                raise ValueError("AC reservation differs from frozen request")
            if fresh:
                try:
                    solver(root, case[-1], run_id=reservation["run_id"], timeout_s=spec.timeout_s)
                except Exception as exc:  # noqa: BLE001 - reservation remains charged, no retry
                    study.write(f"launch-error-{index}", {"error_type": type(exc).__name__})
            row = observe(root, spec, commitment, case, reservation)
            if study.exists(f"launch-error-{index}"):
                row["launch_error_type"] = study.read(f"launch-error-{index}")["error_type"]
            if study.exists(output):
                if study.read(output) != row:
                    raise ValueError("Committed AC snapshot evidence changed")
            else:
                study.write(output, row)
            observed.append(row)
        requested = {(s.hour, s.outage_line) for s in spec.snapshots}
        all_cases = {(t, None) for t in range(len(commitment.demand_mw))}
        if commitment.network.security is not None:
            all_cases.update((t, line) for t in range(len(commitment.demand_mw))
                             for line in commitment.network.security.outage_lines)
        report = {"study_id": identifier, "protocol": PROTOCOL, "phase": "ac_cross_check_finished",
                  "dc_study_id": spec.commitment_study_id, "dc_report_sha256": report_sha,
                  "completed": all(row["passed"] for row in observed),
                  "full_dc_schedule_coverage": requested == all_cases and not (
                      commitment.network.security is not None and commitment.network.security.outage_units),
                  "snapshots": observed, "reserved_solver_runs": len(cases),
                  "scope": "selected_steady_state_ac_snapshots_no_dynamic_security"}
        if study.exists("report"):
            if study.read("report") != report:
                raise ValueError("Committed AC cross-check report changed")
        else:
            study.write("report", report)
        return report
