import pytest

from gridagent import ac_native_collection as collection
from gridagent.ac_check_ir import ACCheckSpec, validate_mapping
from gridagent.ac_collection_families import FAMILIES, RUNS_PER_CASE, SPLITS, CollectionSpec, build_case, plan
from gridagent.ac_decision_dataset import build_dataset, family_identity
from gridagent.commitment_ir import UnitCommitment
from gridagent.math_program_router import solve, verify
from gridagent.standard_ac_benchmark import NETWORKS, manifest_for, run_benchmark


def auth():
    return {"families": ["grid-03"], "levels": ["nominal"], "max_dc_calls": 1,
            "max_ac_runs": RUNS_PER_CASE}


def test_all_families_map_and_solve_dc():
    identities = set()
    for family in FAMILIES:
        case = build_case(family, "nominal")
        dc = UnitCommitment.model_validate(case["dc"])
        ac = ACCheckSpec.model_validate(case["ac_template"])
        assert validate_mapping(ac, dc) == dc
        assert verify(dc, solve(dc))["primal"]["passed"]
        identities.add(family_identity(ac))
        assert case["split"] == SPLITS[family]
        assert ac.model.model_id == family
    assert len(identities) == len(FAMILIES)
    assert list(SPLITS.values()).count("validation") == 8


def test_family_levels_stay_in_same_split_and_plan_is_canonical():
    raw = {"families": ["grid-03", "grid-08"], "levels": ["heavy", "light"],
           "max_dc_calls": 4, "max_ac_runs": 4*RUNS_PER_CASE}
    a = CollectionSpec.model_validate(raw)
    assert len(plan(a)) == 4
    for case in plan(a):
        assert case["split"] == SPLITS[case["family"]]
    raw["families"].reverse()
    raw["levels"].reverse()
    assert plan(a) == plan(raw)


@pytest.mark.parametrize("change", [{"families": ["unknown"]}, {"levels": ["nominal", "nominal"]},
                                   {"max_ac_runs": 1}, {"families": ["grid-03", "grid-04"]}])
def test_collection_rejects_invalid_budget_or_pool(change):
    with pytest.raises(ValueError):
        CollectionSpec.model_validate({**auth(), **change})


def test_interrupted_case_not_relaunched(tmp_path, monkeypatch):
    identifier = collection.start_collection(tmp_path, auth())

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(collection, "collect_case", interrupt)
    with pytest.raises(KeyboardInterrupt):
        collection.resume_collection(tmp_path, identifier)
    monkeypatch.setattr(collection, "collect_case", lambda *a, **kw: pytest.fail("Repeated case"))
    report = collection.resume_collection(tmp_path, identifier)
    assert report["cases"][0]["status"] == "interrupted_case"
    assert report["reserved_dc_calls"] == 1
    assert report["reserved_ac_runs"] == RUNS_PER_CASE
    assert report["dataset_authorization"] is None
    assert collection.resume_collection(tmp_path, identifier) == report


def test_standard_network_screening_contracts():
    for network in NETWORKS:
        manifest = manifest_for(network)
        assert manifest.program.base == network
        assert [s.load_scale for s in manifest.scenarios] == [1, 1.1]
        assert manifest.max_runs == 2 and manifest.max_repairs == 0
    with pytest.raises(ValueError):
        manifest_for("unknown")


@pytest.mark.integration
def test_native_collection_replays_and_produces_labeled_pool(tmp_path):
    pytest.importorskip("pandapower")
    raw = {**auth(), "families": ["grid-03", "grid-04", "grid-08"], "max_dc_calls": 3,
           "max_ac_runs": 3*RUNS_PER_CASE}
    identifier = collection.start_collection(tmp_path, raw)
    report = collection.resume_collection(tmp_path, identifier)
    assert report["eligible_cases"] == 3, report
    assert report["all_splits_represented"]
    assert report["observed_ac_runs"] == 3*RUNS_PER_CASE
    dataset = build_dataset(tmp_path, report["dataset_authorization"])
    assert {row["split"] for row in dataset["rows"]} == {"train", "validation", "test"}
    assert {row["y"] for row in dataset["rows"]} == {0, 1}
    assert collection.resume_collection(tmp_path, identifier) == report


@pytest.mark.integration
def test_standard_case14_screening_records_native_evidence(tmp_path):
    pytest.importorskip("pandapower")
    report = run_benchmark(tmp_path, ["case14"])
    row = report["observations"][0]
    assert row["network"] == "case14"
    assert row["reserved_runs"] == 2
    assert len(row["scenarios"]) == 2
