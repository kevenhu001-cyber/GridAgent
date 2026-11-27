"""Independent polar AC equation solver for public balanced power-flow cases.

The input conversion is shared with pandapower; no pandapower numerical result
is used to initialize or solve the reference equations.
"""

import numpy as np
from scipy.optimize import root

PROTOCOL = "public-ac-numerical-reference-v1"
VOLTAGE_TOL = 1e-6
ANGLE_TOL_DEG = 1e-4
RESIDUAL_TOL_PU = 1e-8


def solve_reference(case):
    bus = np.asarray(case["bus"]).real
    gen = np.asarray(case["gen"]).real
    branch = np.asarray(case["branch"]).real
    base = float(case["baseMVA"])
    n = len(bus)
    if not np.isfinite(base) or base <= 0 or not 2 <= n <= 500:
        raise ValueError("Unsupported reference network size or base")
    if not np.isfinite(bus[:, :13]).all() or not np.isfinite(gen[:, :10]).all():
        raise ValueError("Nonfinite bus or generator input")
    ids = bus[:, 0].astype(int)
    if len(set(ids)) != n or not np.array_equal(ids, bus[:, 0]):
        raise ValueError("Invalid reference bus identities")
    lookup = {key: i for i, key in enumerate(ids)}
    kind = bus[:, 1]
    slack = np.flatnonzero(kind == 3)
    pq = np.flatnonzero(kind == 1)
    pv = np.flatnonzero(kind == 2)
    if len(slack) != 1 or len(pq) + len(pv) + 1 != n:
        raise ValueError("Reference supports a single slack and active PQ/PV buses")
    nonref = np.flatnonzero(kind != 3)
    y = np.diag((bus[:, 4] + 1j * bus[:, 5]) / base)
    for row in branch:
        if row[10] <= 0:
            continue
        if not np.isfinite(row[[0, 1, 2, 3, 4, 8, 9, 10]]).all():
            raise ValueError("Nonfinite branch input")
        f, t = lookup[int(row[0])], lookup[int(row[1])]
        z = complex(row[2], row[3])
        if f == t or abs(z) < 1e-12:
            raise ValueError("Unsupported zero impedance or self-loop")
        series = 1 / z
        shunt = 0.5j * row[4]
        tap = (row[8] or 1.0) * np.exp(1j * np.deg2rad(row[9]))
        y[f, f] += (series + shunt) / abs(tap)**2
        y[f, t] -= series / np.conj(tap)
        y[t, f] -= series / tap
        y[t, t] += series + shunt
    specified = -(bus[:, 2] + 1j * bus[:, 3]) / base
    vm = np.ones(n)
    va = np.zeros(n)
    va[slack] = np.deg2rad(bus[slack, 8])
    regulated = {}
    for row in gen:
        if row[7] <= 0:
            continue
        i = lookup[int(row[0])]
        specified[i] += complex(row[1], row[2]) / base
        if kind[i] in (2, 3):
            if i in regulated and not np.isclose(regulated[i], row[5], atol=1e-9, rtol=0):
                raise ValueError("Conflicting voltage setpoints")
            regulated[i] = row[5]
            vm[i] = row[5]
    if set(regulated) != set(np.r_[slack, pv]) or (vm <= 0).any():
        raise ValueError("Missing or invalid regulated voltage")
    def voltage(x):
        angle, magnitude = va.copy(), vm.copy()
        angle[nonref] = x[:len(nonref)]
        magnitude[pq] = x[len(nonref):]
        return magnitude * np.exp(1j * angle), magnitude, angle

    def mismatch(x):
        v, _, _ = voltage(x)
        delta = v * np.conj(y @ v) - specified
        return np.r_[delta.real[nonref], delta.imag[pq]]

    initial = np.r_[np.zeros(len(nonref)), np.ones(len(pq))]
    result = root(mismatch, initial, method="hybr", options={"xtol": 1e-10, "maxfev": 10000})
    _, magnitude, angle = voltage(result.x)
    residual = float(np.max(np.abs(mismatch(result.x))))
    if (not np.isfinite(result.x).all() or not np.isfinite(residual)
            or residual > RESIDUAL_TOL_PU or (magnitude <= 0).any()):
        raise ValueError("Independent reference solve failed residual or voltage check")
    return {"bus_ids": ids.tolist(), "vm_pu": magnitude.tolist(), "va_degree": np.rad2deg(angle).tolist(),
            "slack_bus_id": int(ids[slack[0]]), "max_residual_pu": residual, "evaluations": int(result.nfev)}


def compare_solution(reference, observed, bus_mapping):
    """Require a bijective native bus mapping; remove arbitrary angle reference."""
    ids = reference["bus_ids"]
    if set(bus_mapping) != set(observed) or set(bus_mapping.values()) != set(ids):
        raise ValueError("Reference bus coverage mismatch")
    if len(bus_mapping) != len(ids):
        raise ValueError("Reference bus mapping is not bijective")
    index = {key: i for i, key in enumerate(ids)}
    slack = next(key for key, value in bus_mapping.items() if value == reference["slack_bus_id"])
    angle_offset = observed[slack][1] - reference["va_degree"][index[bus_mapping[slack]]]
    voltage_errors, angle_errors = [], []
    for key, internal in bus_mapping.items():
        i = index[internal]
        vm, va = observed[key]
        if not np.isfinite([vm, va]).all():
            raise ValueError("Nonfinite native voltage")
        voltage_errors.append(abs(vm-reference["vm_pu"][i]))
        difference = va-angle_offset-reference["va_degree"][i]
        angle_errors.append(abs((difference+180) % 360-180))
    vmax, amax = max(voltage_errors), max(angle_errors)
    return {"passed": bool(vmax <= VOLTAGE_TOL and amax <= ANGLE_TOL_DEG),
            "buses": len(ids), "max_voltage_error_pu": vmax, "max_angle_error_deg": amax,
            "voltage_tolerance_pu": VOLTAGE_TOL, "angle_tolerance_deg": ANGLE_TOL_DEG}


def compare_public_run(workspace, network, scale, run_id):
    import pandas as pd
    import pandapower as pp
    from pandapower import networks
    from pandapower.converter import to_ppc

    from .native_program import PPProgram
    from .workspace import artifact_folder, load_object

    if network not in ("case14", "case39", "case118") or scale not in (1, 1.1):
        raise ValueError("Unsupported public reference scenario")
    folder = artifact_folder(workspace, "runs", run_id)
    request = PPProgram.model_validate(load_object(folder / "request.json"))
    expected = PPProgram(base=network, load_scale=scale)
    if request != expected:
        raise ValueError("Native run input differs from reference scenario")
    result = load_object(folder / "result.json")
    if result.get("status") != "ok" or result.get("version") != pp.__version__:
        raise ValueError("Native result missing or backend version differs")
    # Rebuild from the named factory, not from result files.
    net = getattr(networks, network)()
    net.load["scaling"] *= scale
    converted = to_ppc(net, calculate_voltage_angles=True, trafo_model="t",
                       check_connectivity=True, init="flat", mode="pf")
    reference = solve_reference(converted)
    mapping = {int(i): int(net._pd2ppc_lookups["bus"][i]) for i in net.bus.index}
    frame = pd.read_csv(folder / "res_bus.csv", index_col=0)
    if not frame.index.is_unique:
        raise ValueError("Duplicate native bus results")
    observed = {int(i): (float(row.vm_pu), float(row.va_degree)) for i, row in frame.iterrows()}
    return {**compare_solution(reference, observed, mapping), "protocol": PROTOCOL,
            "reference_residual_pu": reference["max_residual_pu"],
            "reference_evaluations": reference["evaluations"], "pandapower_version": pp.__version__,
            "scope": "independent numerical equations; shared network conversion; no independent input certification"}
