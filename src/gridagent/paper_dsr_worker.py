"""Execute pinned PowerFactory driver in its licensed interpreter."""
import json
import sys
from pathlib import Path
from uuid import uuid4


def main():
    folder = Path(sys.argv[1])
    request = json.loads((folder / "request.json").read_text(encoding="utf-8"))
    sys.path.insert(0, request["binding"])
    sys.path.insert(0, str(Path(request["driver"]).parent))
    from Agent_DIgSILENT import DIgSILENTAgent, SimulationConfig

    location = request["location"]
    fault_type = location.split()[0].lower()
    suffix = ".ElmTerm" if fault_type == "bus" else ".ElmLne"
    unique = "GridAgent_" + uuid4().hex
    cfg = SimulationConfig(project_path=request["project_path"], base_study_case=request["base_study_case"],
                           study_case=unique, fault_type=fault_type, fault_element=location + suffix,
                           t_fault=1.0, t_clear=1 + request["duration_ms"] / 1000,
                           t_end=10.0, dt_rms=0.01, output_dir=str(folder), run_label=unique,
                           result_name=request["result_name"], open_digsilent=0, export_pfd=0,
                           run_review_agent=0, run_final_report_agent=0, run_mitigation_agent=0,
                           word_document=0, final_word_document=0, final_presentation=0)
    agent = DIgSILENTAgent(cfg)
    try:
        report = agent.run_pipeline()
        if report.get("success"):
            result = {"status": "ok", "csv_path": report["csv_path"]}
        else:
            result = {"status": "failed", "reason": "Original PowerFactory pipeline failed"}
        (folder / "worker-result.json").write_text(json.dumps(result), encoding="utf-8")
    finally:
        DIgSILENTAgent.close()


if __name__ == "__main__":
    main()
