"""Versioned diagnostic relations, independent of retrieval or model-provider output.

Original engineering heuristics; not expert-reviewed or statistical causal evidence.
"""
from dataclasses import dataclass

VERSION = "engineering-diagnosis-rules-v1"


@dataclass(frozen=True)
class Rule:
    category: str
    symptom: str
    hypotheses: tuple[str, ...]
    discriminate: tuple[str, ...]
    references: tuple[str, ...] = ()


RULES = {
    "missing_evidence": Rule("evidence", "The required result or independently verifiable artifact is unavailable.",
        ("Interrupted execution or missing native artifacts", "Result identity or artifact completeness failure"),
        ("Inspect the reservation, native status and exact request fingerprint before considering a fresh run.",)),
    "model_fidelity": Rule("model", "The model or evidence does not match the authorized input.",
        ("Wrong model revision or device mapping", "Invalid or changed output artifacts"),
        ("Compare immutable source, compiled request and artifact fingerprints; do not repair the physical model first.",)),
    "solver_nonconvergence": Rule("numerical", "Solver did not provide a converged result.",
        ("Invalid or poorly scaled operating point", "Infeasible or ill-conditioned physical equations",
         "Numerical iteration limit or backend failure"),
        ("Inspect native termination and model topology; compare a separately authorized baseline operating point.",
         "Only after input checks, vary the numerical initialization within an explicit run budget.")),
    "infeasibility_reported": Rule("feasibility", "Solver reports infeasibility; no independent infeasibility certificate.",
        ("Conflicting capacity, balance or chronology constraints", "Insufficient reserve or network transfer",
         "Incorrect units, bounds or model formulation"),
        ("Inspect bounds, demand, initial conditions and compiled equations.",
         ("For a separately authorized diagnostic model, compare base-only and individual contingency cases; "
          "do not relax the original acceptance criteria."))),
    "solver_limit": Rule("numerical", "Solver stopped at a resource or iteration limit without a verified candidate.",
        ("Insufficient evaluation or time budget", "Difficult or poorly scaled formulation"),
        ("Review callback/node counts, model scale and termination; a new solve requires a separately authorized budget.",)),
    "primal_bounds": Rule("mathematical", "Returned variable violates its explicit bounds.",
        ("Incorrect solution decoding", "Tolerance or scaling mismatch"),
        ("Check the named variable, unit and frozen lower/upper bounds.",)),
    "primal_integrality": Rule("mathematical", "Returned integer or binary variable is nonintegral.",
        ("Relaxed problem solved or wrong domain", "Numerical tolerance or decoding issue"),
        ("Compare the declared variable type and compiled integrality vector.",)),
    "primal_row": Rule("mathematical", "A named mathematical constraint is violated.",
        ("Invalid candidate", "Scaling or model-to-row mapping problem"),
        ("Recompute the exact row activity and compare both bounds; do not infer its physical role from its name.",)),
    "objective": Rule("mathematical", "Independent objective or cost does not agree with the result.",
        ("Cost coefficient or interval conversion mismatch", "Incorrect objective sign or result decoding"),
        ("Recompute cost term by term from the frozen coefficients and actual decision variables.",)),
    "voltage": Rule("ac_voltage", "AC voltage falls outside an authorized range.",
        ("Reactive-power deficit or surplus", "Voltage setpoint mismatch", "Large voltage drop across network impedance"),
        ("Locate affected buses; inspect Q output, limits, voltage setpoints and branch loading.",
         "Compare a separately authorized reactive-injection or load-level sensitivity case while keeping limits fixed.")),
    "reactive": Rule("ac_reactive", "Actual reactive output or fixed PQ demand violates its authorization.",
        ("PV voltage setpoint requires unavailable reactive capability", "Incorrect reactive demand or capability input"),
        ("Inspect actual Q against declared limits; compare authorized voltage setpoint or reactive support alternatives.",
         "Do not declare feasibility by allowing unbounded reactive output.")),
    "loading": Rule("network", "An AC or DC branch limit is violated.",
        ("Transfer concentrated on limited branches", "Contingency redistributes power", "Incorrect branch rating or units"),
        ("Identify affected branch and both terminal flows; inspect topology and rating provenance.",
         "Compare authorized base and outage scenarios with the same ratings and demand.")),
    "balance": Rule("balance", "An independently calculated power or energy balance fails.",
        ("Missing injection or sign/unit mismatch", "Incorrect topology or operating-point mapping",
         "Solver or result coverage issue"),
        ("Reconstruct injections, withdrawals and branch losses by bus and time; inspect missing/duplicate equipment.")),
    "slack": Rule("ac_dispatch", "Mapped AC dispatch or capacity cannot reproduce the authorized schedule.",
        ("Network losses exceed available balancing headroom", "DC approximation differs from AC flows",
         "Incorrect active-power mapping"),
        ("Compare scheduled and actual P for each unit, slack deviation and summed passive losses.",
         "Check reserve and capacity before authorizing any redispatch.")),
    "storage": Rule("storage", "Storage energy, capacity or operating-mode constraint fails.",
        ("MW/MWh or efficiency convention mismatch", "Inconsistent initial/terminal SOC", "Simultaneous charge/discharge"),
        ("Reconstruct SOC chronologically from charge/discharge, interval length and efficiency; compare terminal target.",
         ), ("official:pypsa:1.2.4:StorageUnit",)),
    "chronology": Rule("commitment", "Thermal unit chronology, capacity or ramp constraint fails.",
        ("Incorrect initial online duration or power", "Inconsistent min up/down or ramp limits",
         "Invalid startup/shutdown transition"),
        ("Rebuild the hourly on/start/stop sequence from initial state, then compare ramp and dwell limits.",)),
    "reserve": Rule("security", "Reserve or corrective redispatch constraint fails.",
        ("Insufficient surviving online headroom", "Response ramp limit or reserve eligibility",
         "Transmission bottleneck in the selected contingency"),
        ("Inspect per-unit allocated versus usable reserve, actual redispatch and post-outage line flows.",
         "Compare individual authorized contingencies; failed equipment must not supply reserve.")),
    "outage": Rule("security", "Failed equipment has nonzero flow/output or remains in service.",
        ("Incorrect outage mapping or topology update", "Result belongs to a different scenario"),
        ("Compare outage device ID, frozen scenario and native in-service status; check zero flow/output.")),
    "optimality": Rule("optimality", "An independent LP certificate or requested KKT diagnostic did not pass.",
        ("Candidate is feasible but not stationary/optimal", "Ill-conditioning or inaccurate multipliers"),
        ("Review primal-dual gap, stationarity and scaling; compare authorized initial points or solver settings.")),
    "unclassified": Rule("unknown", "An independent check failed without a matching diagnostic relation.",
        ("Cause not established by the available evidence",),
        ("Inspect the exact check definition and its source data before proposing changes.",)),
}


def rule_for(scope, key):
    """Use only known verifier namespaces; generic user-defined row names have no physical semantics."""
    if key in {"evidence_integrity", "model_input_fidelity"}:
        return "model_fidelity"
    if scope == "mathematical":
        if key.startswith("bounds:"):
            return "primal_bounds"
        if key.startswith("integer:"):
            return "primal_integrality"
        if key.startswith("row:"):
            return "primal_row"
        if key == "objective":
            return "objective"
    elif scope == "ac_native":
        if key in {"voltage_operating_range", "positive_voltage"}:
            return "voltage"
        if key in {"res_line_loading", "res_trafo_loading"}:
            return "loading"
        if key == "power_balance_mva":
            return "balance"
        if key == "active_bus_coverage":
            return "model_fidelity"
        if key == "solver_success":
            return "solver_nonconvergence"
    elif scope == "ac_physical":
        if key.startswith(("reactive:", "q:")):
            return "reactive"
        if key.startswith("active-limit:"):
            return "loading"
        if key.startswith("outage:"):
            return "outage"
        if key.startswith(("outage-up:", "outage-down:")):
            return "reserve"
        if key.startswith(("capacity:", "dispatch:")):
            return "slack"
        if key.startswith(("p:", "passive-loss:")) or key == "loss-reconciliation":
            return "balance"
    elif scope == "commitment":
        if key == "operating_cost":
            return "objective"
        if key.startswith("storage:"):
            return "storage"
        if key.startswith("unit:"):
            return "chronology"
        if key.startswith(("balance:", "node:")):
            return "balance"
        if key.startswith("line:"):
            return "loading" if key.endswith((":capacity", ":angle")) else "balance"
        if key.startswith("reserve:"):
            return "reserve"
        if key.startswith(("security:", "unit-security:")):
            if key.endswith(":outage"):
                return "outage"
            if ":unit:" in key:
                return "reserve"
            if ":line:" in key and key.endswith((":capacity", ":angle")):
                return "loading"
            if ":node:" in key or key.endswith(":dc"):
                return "balance"
    return "unclassified"
