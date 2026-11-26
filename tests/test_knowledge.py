from langchain_core.tools import tool

from gridagent.domain import ScenarioRequest
from gridagent.knowledge import KnowledgeIndex, contracts


@tool(args_schema=ScenarioRequest)
def scenario_power_flow(**kwargs):
    """Run a bounded load and line scenario."""
    return kwargs


@tool
def inspect_case(case: str):
    """Inspect model and topology."""
    return case


def test_function_option_triples_and_dependency():
    index = KnowledgeIndex(contracts({"scenario_power_flow": scenario_power_flow, "inspect_case": inspect_case}))
    result = index.retrieve({"functions": ["scenario_power_flow"],
                             "options": [{"description": "load_scale", "value": "1.1",
                                          "function": "scenario_power_flow"}]})
    assert result["functions"][0]["id"] == "scenario_power_flow"
    option = result["options"][0]
    assert option["id"] == "scenario_power_flow.load_scale"
    assert option["schema"]["minimum"] == 0.5 and option["schema"]["maximum"] == 1.5
    assert option["requested_value"] == "1.1"
    assert "inspect_case" in result["dependencies"]
    assert index.feedback("scenario_power_flow", ["load_scale"])["contracts"][1]["option"] == "load_scale"


def test_function_scope_prevents_cross_function_options():
    index = KnowledgeIndex(contracts({"scenario_power_flow": scenario_power_flow, "inspect_case": inspect_case}))
    result = index.retrieve({"options": [{"description": "case", "function": "inspect_case"}]})
    assert result["options"][0]["id"] == "inspect_case.case"
