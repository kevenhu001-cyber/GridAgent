"""Versioned original summaries with direct links to official solver manuals."""
REFERENCES = (
    ("pandapower", "3.3.3", "pandapower_program", "create_transformer_from_parameters",
     "Transformer · create function", "https://pandapower.readthedocs.io/en/v3.3.3/elements/trafo.html",
     ("For a two-winding transformer, provide both rated voltages, rated MVA and short-circuit impedance. "
     "Model a ratio tap changer with its side, neutral, position, step percentage and permitted range.")),
    ("pandapower", "3.3.3", "pandapower_program", "create_switch",
     "Switch · create function", "https://pandapower.readthedocs.io/en/v3.3.3/elements/switch.html",
     ("Use et=b for a bus tie, l for a line terminal and t for a transformer terminal. A closed ideal bus tie "
     "couples two buses into one electrical node, while a terminal switch controls the connected branch terminal.")),
    ("pandapower", "3.3.3", "pandapower_program", "calc_sc",
     "Short circuit", "https://pandapower.readthedocs.io/en/v3.3.3/shortcircuit/run.html",
     ("For a three-phase calculation, select the fault bus and maximum or minimum case. Feed short-circuit "
     "power and R/X source data into the equivalent network; interpret ikss_ka as initial current.")),
    ("andes", "2.0.0", "simulate_fault", "Fault",
     "Time-Domain Simulation", "https://docs.andes.app/en/v2.0.0/tutorials/04-time-domain.html",
     ("The initial operating point comes from a solved power flow. Declare disturbance start and clearing "
     "times before setup and retain a post-clearing simulation interval to inspect recovery.")),
    ("andes", "2.0.0", "eigenanalysis", "EIG",
     "Eigenvalue Analysis", "https://docs.andes.app/en/v2.0.0/tutorials/07-eigenvalue-analysis.html",
     ("Compute small-signal modes around the solved operating point. Track the real part and damping ratio "
     "across controller settings and treat near-zero reference modes separately from growing modes.")),
    ("andes", "2.0.0", "andes_governor_eigen", "TGOV1",
     "Parameter Sweeps and Batch Processing", "https://docs.andes.app/en/v2.0.0/tutorials/08-parameter-sweeps.html",
     ("Compare parameter settings using separate fresh model instances and record the modified setting "
     "alongside each output. GridAgent currently exposes bounded TGOV1 droop and time-constant edits.")),
    ("pypsa", "1.2.4", "pypsa_dispatch", "Line",
     "Line", "https://docs.pypsa.org/v1.2.4/user-guide/components/lines/",
     ("A passive AC line has terminal buses, series impedance in ohms and an apparent-power rating. "
     "For linear dispatch, the active flow is bounded by that rating and coupled to bus angles.")),
    ("pypsa", "1.2.4", "pypsa_dispatch", "StorageUnit",
     "Storage Unit", "https://docs.pypsa.org/v1.2.4/user-guide/components/storage-units/",
     ("A storage unit couples energy capacity with power rating via max_hours. Charging and discharge "
     "efficiencies act in distinct directions, and cyclic state of charge wraps across the chosen horizon.")),
    ("pypsa", "1.2.4", "pypsa_dispatch", "optimize",
     "Optimization usage", "https://docs.pypsa.org/v1.2.4/user-guide/optimization/overview/",
     ("Fix snapshots and per-snapshot demand before optimizing. Record native solver status and verify "
     "balance and constraint satisfaction from exported time series.")),
)


def official_rows():
    return [{"id": f"official:{backend}:{version}:{option}", "kind": "reference", "reference_kind": "option",
             "function": function, "option": option, "backend": backend, "version": version, "chapter": chapter,
             "description": summary, "source": source,
             "authority": "GridAgent summary of official documentation; tool schemas define allowed inputs",
             "rights": "Original summary. Upstream manual linked; upstream text and examples are not redistributed."}
            for backend, version, function, option, chapter, source, summary in REFERENCES]
