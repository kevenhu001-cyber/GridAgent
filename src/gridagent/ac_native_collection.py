"""Bounded prospective collection of replayable native DC/AC experiment studies."""

import argparse
import json
from pathlib import Path

from .ac_check import resume_ac_check, start_ac_check
from .ac_check_ir import ACCheckSpec
from .ac_collection_families import CollectionSpec, plan, plan_fingerprint
from .ac_decision_dataset import DatasetSpec
from .ac_diagnostic_experiment import measure, resume_experiment, start_experiment
from .ac_diagnostic_ir import ACDiagnosticExperiment
from .commitment_ir import UnitCommitment
from .dsr import Study
from .engineering_ir import fingerprint
from .math_program_tasks import resume_program, start_program

PROTOCOL = "ac-native-collection-v1"


def no_solver(*args, **kwargs):
    raise AssertionError("Collection replay must not launch a solver")


def child(root, parent, index, stage, spec, start, resume, *, fresh, reservations):
    name = f"child-{index}-{stage}"
    if fresh:
        if parent.exists(name):
            raise ValueError("Collection child without fresh case reservation")
        identifier = start(root, spec)
        parent.write(name, {"study_id": identifier, "spec_sha256": spec.sha256()})
    link = parent.read(name)
    study = Study.reopen(root / "studies", link["study_id"])
    manifest = study.read("manifest")
    if link["spec_sha256"] != spec.sha256() or manifest["spec"] != spec.canonical():
        raise ValueError("Collection child input changed")
    if fresh:
        report = resume(root, study.id)
    else:
        if not study.exists("report") or not all(study.exists(key) for key in reservations):
            raise ValueError("Collection child evidence incomplete")
        report = resume(root, study.id, solver=no_solver)
    return study.id, report


def collect_case(root, study, index, case, *, fresh):
    dc_spec = UnitCommitment.model_validate(case["dc"])
    dc_id, dc_report = child(root, study, index, "dc", dc_spec, start_program, resume_program,
                             fresh=fresh, reservations=["reservation-1"])
    row = {"index": index, "family": case["family"], "split": case["split"], "level": case["level"],
           "dc_study_id": dc_id, "dc_report_sha256": fingerprint(dc_report),
           "observed_dc_calls": dc_report["reserved_solver_calls"], "observed_ac_runs": 0}
    if not dc_report["completed"]:
        return {**row, "status": "dc_not_verified"}
    ac_spec = ACCheckSpec.model_validate({**case["ac_template"], "commitment_study_id": dc_id})
    source_id, source_report = child(root, study, index, "source", ac_spec, start_ac_check, resume_ac_check,
                                     fresh=fresh, reservations=["reservation-1", "evaluation-1"])
    row.update(source_study_id=source_id, source_report_sha256=fingerprint(source_report),
               observed_ac_runs=source_report["reserved_solver_runs"])
    spec = ACDiagnosticExperiment.model_validate({
        "source_study_id": source_id, "source_report_sha256": fingerprint(source_report),
        "snapshot": {"hour": 0}, "target_scope": "ac_native", "target_check": "voltage_operating_range",
        "probes": [{"kind": "voltage_setpoint", "device": "slack", "value_pu": value}
                   for value in case["probe_values_pu"]],
        "max_solver_runs": 1+len(case["probe_values_pu"])})
    metric = measure(spec, source_report["snapshots"][0], ac_spec.acceptance)
    if metric is None or metric["passed"]:
        return {**row, "status": "source_target_not_observed"}
    reservations = [f"{prefix}-{i}" for i in range(len(spec.probes)+1)
                    for prefix in ("reservation", "evaluation")]
    fixed_id, fixed = child(root, study, index, "fixed", spec, start_experiment, resume_experiment,
                            fresh=fresh, reservations=reservations)
    row.update(fixed_study_id=fixed_id, fixed_report_sha256=fingerprint(fixed),
               observed_ac_runs=row["observed_ac_runs"]+fixed["reserved_solver_runs"])
    return {**row, "status": "dataset_eligible" if fixed["baseline_reproduced"] else "baseline_not_reproduced"}


def start_collection(root, authorization):
    root = Path(root).resolve()
    auth = CollectionSpec.model_validate(authorization)
    study = Study(root / "studies")
    study.write("manifest", {"protocol": PROTOCOL, "spec": auth.canonical(),
                             "plan_sha256": plan_fingerprint(auth), "cases": plan(auth)})
    return study.id


def resume_collection(root, identifier):
    root = Path(root).resolve()
    study = Study.reopen(root / "studies", identifier)
    with study.lock():
        manifest = study.read("manifest")
        auth = CollectionSpec.model_validate(manifest["spec"])
        cases = plan(auth)
        if (manifest["protocol"] != PROTOCOL or manifest["plan_sha256"] != plan_fingerprint(auth)
                or manifest["cases"] != cases):
            raise ValueError("Frozen collection plan changed")
        rows = []
        for index, case in enumerate(cases):
            reservation, output = f"reservation-{index}", f"evaluation-{index}"
            expected = {"index": index, "case_sha256": fingerprint(case),
                        "reserved_dc_calls": case["reserved_dc_calls"],
                        "reserved_ac_runs": case["reserved_ac_runs"]}
            fresh = not study.exists(reservation)
            if fresh:
                if study.exists(output) or study.exists("report") or any(
                        study.exists(f"child-{index}-{stage}") for stage in ("dc", "source", "fixed")):
                    raise ValueError("Collection evidence without reservation")
                study.write(reservation, expected)
                row = collect_case(root, study, index, case, fresh=True)
            else:
                if study.read(reservation) != expected:
                    raise ValueError("Collection reservation changed")
                previous = study.read(output) if study.exists(output) else None
                if previous is None or previous["status"] == "interrupted_case":
                    # Charge the entire case, do not launch unfinished children.
                    # Preserve pointers for manual inspection without using partial cases as labels.
                    row = {"index": index, "family": case["family"], "split": case["split"],
                           "level": case["level"], "status": "interrupted_case",
                           "linked_children": {stage: study.read(f"child-{index}-{stage}")
                                               for stage in ("dc", "source", "fixed")
                                               if study.exists(f"child-{index}-{stage}")}}
                else:
                    row = collect_case(root, study, index, case, fresh=False)
            if study.exists(output):
                if study.read(output) != row:
                    raise ValueError("Committed collection observation changed")
            elif study.exists("report"):
                raise ValueError("Committed collection report missing observations")
            else:
                study.write(output, row)
            rows.append(row)
        eligible = [{"study_id": row["fixed_study_id"], "family": row["family"], "split": row["split"]}
                    for row in rows if row["status"] == "dataset_eligible"]
        splits = {"cases": eligible}
        ready = {row["split"] for row in eligible} == {"train", "validation", "test"}
        if ready:
            splits = DatasetSpec.model_validate(splits).model_dump(mode="json")
        report = {"study_id": identifier, "protocol": PROTOCOL, "phase": "ac_native_collection_finished",
                  "plan_sha256": manifest["plan_sha256"], "cases": rows,
                  "reserved_dc_calls": sum(case["reserved_dc_calls"] for case in cases),
                  "reserved_ac_runs": sum(case["reserved_ac_runs"] for case in cases),
                  "observed_dc_calls": sum(row.get("observed_dc_calls", 0) for row in rows),
                  "observed_ac_runs": sum(row.get("observed_ac_runs", 0) for row in rows),
                  "eligible_cases": len(eligible), "all_splits_represented": ready,
                  "dataset_authorization": splits if ready else None,
                  "completed": len(eligible) == len(rows),
                  "scope": "synthetic network families with native solver results; no independent real-grid generalization"}
        if study.exists("report"):
            if study.read("report") != report:
                raise ValueError("Committed collection report changed")
        else:
            study.write("report", report)
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("authorization", nargs="?")
    parser.add_argument("--resume")
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    if bool(args.authorization) == bool(args.resume) or (args.resume and args.plan_only):
        parser.error("Specify authorization JSON or --resume ID; --plan-only applies to new plans")
    if args.resume:
        identifier = args.resume
    else:
        with Path(args.authorization).open("rb") as handle:
            raw = handle.read(1024*1024+1)
        if len(raw) > 1024*1024:
            raise ValueError("Collection input exceeds 1 MiB")
        identifier = start_collection(args.workspace, CollectionSpec.model_validate_json(raw))
    report = ({"study_id": identifier, "solver_calls": 0} if args.plan_only
              else resume_collection(args.workspace, identifier))
    print(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
