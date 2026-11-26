"""User-managed ngspice executable and independently verified RC analysis."""
import csv
import json
import math
import re
import subprocess
from itertools import pairwise
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field

from .model_quality import check
from .models import file_digest
from .native_program import Strict
from .plugins import clean_env

CAPABILITY = {"operation": "rc_filter", "analyses": ["transient", "ac"], "inputs": ["resistance_ohm", "capacitance_f"],
              "outputs": ["time_s", "voltage_v", "frequency_hz", "gain", "phase_deg"], "evaluator": "analytic RC"}


class RCFilter(Strict):
    analysis: Literal["transient", "ac"]
    resistance_ohm: float = Field(ge=1, le=1e7)
    capacitance_f: float = Field(ge=1e-10, le=1)


def runtime_status(root):
    try:
        return json.loads((Path(root) / "ngspice-runtime.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def register_ngspice(root, path):
    path = Path(path).expanduser()
    if not path.is_absolute() or path.name.casefold() not in {"ngspice", "ngspice.exe", "ngspice_con.exe"}:
        raise ValueError("Select the absolute path to the ngspice console executable")
    path = path.resolve(strict=True)
    if not path.is_file():
        raise ValueError("Select an ngspice executable file")
    result = subprocess.run([str(path), "--version"], env=clean_env(), stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, errors="replace", timeout=10, check=True)
    match = re.search(r"\bngspice-(\d+(?:\.\d+)*)\b", result.stdout + result.stderr, re.IGNORECASE)
    if match is None:
        raise ValueError("The executable did not report an ngspice version")
    info = {"path": str(path), "version": match[1], "sha256": file_digest(path)}
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    stage = root / (".ngspice-" + uuid4().hex)
    try:
        stage.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
        stage.replace(root / "ngspice-runtime.json")
    finally:
        stage.unlink(missing_ok=True)
    return info


def raw_samples(path, complex_values):
    if path.stat().st_size > 1_000_000:
        raise ValueError("ngspice output exceeds the rawfile limit")
    text = path.read_text(encoding="ascii")
    header, marker, values = text.partition("Values:")
    if not marker or not re.search(r"^No\. Variables:\s+2\s*$", header, re.MULTILINE):
        raise ValueError("Invalid ngspice rawfile variable count")
    lines = [line.strip() for line in values.splitlines() if line.strip()]
    if not 10 <= len(lines)//2 <= 2000 or len(lines) % 2:
        raise ValueError("Invalid ngspice sample count")

    def value(raw):
        if complex_values:
            re_part, im_part = raw.split(",")
            return complex(float(re_part), float(im_part))
        return float(raw)

    samples = []
    for offset in range(0, len(lines), 2):
        index, axis = lines[offset].split(maxsplit=1)
        if int(index) != offset//2:
            raise ValueError("Invalid ngspice point order")
        coordinate, response = float(value(axis).real), value(lines[offset+1])
        if not all(math.isfinite(x) for x in (coordinate, response.real, response.imag)):
            raise ValueError("Non-finite ngspice sample")
        samples.append((coordinate, response))
    if any(left[0] >= right[0] for left, right in pairwise(samples)):
        raise ValueError("ngspice axis is not strictly increasing")
    return samples


def run_rc(root, parameters):
    spec = RCFilter.model_validate(parameters)
    profile = runtime_status(root)
    if not profile:
        raise ValueError("Register the ngspice runtime before running an RC experiment")
    path = Path(profile["path"])
    if file_digest(path) != profile["sha256"]:
        raise ValueError("ngspice executable changed; register it again")
    identifier = uuid4().hex
    folder = Path(root) / "runs" / identifier
    folder.mkdir(parents=True)
    tau = spec.resistance_ohm * spec.capacitance_f
    stop, step, rise = 5*tau, tau/100, tau/10000
    corner = 1/(2*math.pi*tau)
    transient = spec.analysis == "transient"
    source = f"PULSE(0 1 0 {rise:.12g} {rise:.12g} {2*stop:.12g} {4*stop:.12g})" if transient else "AC 1"
    analysis = (f".tran {step:.12g} {stop:.12g} 0 {step:.12g} uic" if transient
                else f".ac dec 20 {corner/100:.12g} {corner*100:.12g}")
    netlist = f"GridAgent RC\nVin in 0 {source}\nR1 in out {spec.resistance_ohm:.12g}\n"
    netlist += f"C1 out 0 {spec.capacitance_f:.12g}\n.save v(out)\n{analysis}\n.end\n"
    (folder / "request.json").write_text(spec.model_dump_json(), encoding="utf-8")
    (folder / "circuit.cir").write_text(netlist, encoding="ascii")
    env = {**clean_env(), "SPICE_ASCIIRAWFILE": "1"}
    try:
        with (folder / "solver.log").open("w", encoding="utf-8") as log:
            subprocess.run([str(path), "-n", "-b", "-r", "response.raw", "circuit.cir"], cwd=folder, env=env,
                           stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, check=True, timeout=30)
        samples = raw_samples(folder / "response.raw", not transient)
        if transient:
            errors = [abs(value - (-math.expm1(-time/tau))) for time, value in samples]
            rows = samples
            columns = ("time_s", "voltage_v")
            complete = samples[0][0] <= step and samples[-1][0] >= 0.99*stop
        else:
            errors = [abs(value - 1/(1+2j*math.pi*frequency*tau)) for frequency, value in samples]
            rows = [(frequency, abs(value), math.degrees(math.atan2(value.imag, value.real)))
                    for frequency, value in samples]
            columns = ("frequency_hz", "gain", "phase_deg")
            complete = samples[0][0] <= corner/99 and samples[-1][0] >= 99*corner
        error = max(errors)
        checks = [check("axis_coverage", complete), check("analytic_rc_response", error <= 0.003, error, 0.003)]
        result = {"status": "ok", "quality": {"passed": all(row["passed"] for row in checks), "tests": checks}}
        with (folder / "rc_response.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(columns)
            writer.writerows(rows)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        result = {"status": "failed", "reason": type(exc).__name__, "quality": {"passed": False}}
    result.update(backend="ngspice", version=profile["version"], run_id=identifier, operation=spec.analysis, case="RC")
    (folder / "result.json").write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
    return result
