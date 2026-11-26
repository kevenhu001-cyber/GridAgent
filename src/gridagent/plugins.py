"""First-party opt-in solver extensions. No executable third-party manifests."""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from importlib.metadata import distributions
from pathlib import Path
from uuid import uuid4

from filelock import FileLock

CATALOG = {
    "pypower": {"title": "PYPOWER", "packages": ["PYPOWER>=5.1.19,<6"],
                "modules": ["pypower"], "tools": ["pypower_case_flow"],
                "prompt": "Use pypower_case_flow for AC flow on bundled IEEE14/30/118 cases; p.u. voltage, degrees. Do not claim user case conversion."},
    "pypowsybl": {"title": "PyPowSyBl", "packages": ["pypowsybl>=1.10,<3"],
                 "modules": ["pypowsybl"], "tools": ["powsybl_case_flow"],
                 "prompt": "Use powsybl_case_flow for independent IEEE14 AC flow. Voltage is kV, not p.u.; native case variants may differ."},
    "osqp": {"title": "OSQP", "packages": ["osqp>=1,<2"],
             "modules": ["osqp"], "tools": ["ramp_tracking_qp"],
             "prompt": "Use ramp_tracking_qp for bounded ramp-limited least-squares tracking. MW per hourly step; no SOC or energy balance."},
    "scikit-rf": {"title": "scikit-rf", "packages": ["scikit-rf>=1.6,<2"],
                  "modules": ["skrf"], "tools": ["transmission_line_sparameters"],
                  "prompt": "Use transmission_line_sparameters for uniform linear line S parameters; Hz, m, ohms, nepers/m and m/s; phase in radians."},
    "coolprop": {"title": "CoolProp", "packages": ["CoolProp>=7,<9"],
                 "modules": ["CoolProp"], "tools": ["fluid_thermophysical_state"],
                 "prompt": "Use fluid_thermophysical_state for equilibrium properties at K and Pa. Not CFD or thermal simulation."},
    "rainflow": {"title": "rainflow", "packages": ["rainflow>=3.2,<4"],
                 "modules": ["rainflow"], "tools": ["rainflow_cycle_count"],
                 "prompt": "Use rainflow_cycle_count on sampled scalar histories. Counts half/full cycles by range, not equivalent battery throughput or lifetime."},
    "windpowerlib": {"title": "windpowerlib", "packages": ["windpowerlib>=0.2,<1"],
                     "modules": ["windpowerlib"], "tools": ["wind_power_curve"],
                     "prompt": "Use wind_power_curve for turbine power from a user-provided curve in m/s and W; no wake or weather prediction."},
    "cvxpy": {"title": "CVXPY", "packages": ["cvxpy>=1.6,<2"],
              "modules": ["cvxpy"], "tools": ["quadratic_dispatch"],
              "prompt": "Use quadratic_dispatch for convex single-period economic dispatch with nonnegative quadratic costs, MW and cost per hour. No network or commitment."},
    "pyomo": {"title": "Pyomo + HiGHS", "packages": ["pyomo>=6.9,<7", "highspy>=1.7,<2"],
              "modules": ["pyomo", "highspy"], "tools": ["unit_commitment"],
              "prompt": "Use unit_commitment for hourly single-bus MILP with start and online costs, initially off units. No ramp, minimum up/down or reserve."},
    "casadi": {"title": "CasADi", "packages": ["casadi>=3.6,<4"],
               "modules": ["casadi"], "tools": ["equivalent_cell_response"],
               "prompt": "Use equivalent_cell_response for constant-current Thevenin RC voltage dynamics, fixed OCV, zero initial polarization. Not electrochemical or thermal simulation."},
    "pvlib": {"title": "pvlib", "packages": ["pvlib>=0.13,<0.17"], "modules": ["pvlib"],
              "tools": ["solar_dc_power"], "prompt": "Use solar_dc_power for PVWatts DC power from effective irradiance W/m2, cell temperature C and rated W. Not AC output or weather prediction."},
    "pypsa": {"title": "PyPSA + HiGHS", "packages": ["pypsa>=1.0,<1.3", "highspy>=1.7,<2"],
              "modules": ["pypsa", "highspy"], "tools": ["pypsa_dispatch"],
              "prompt": "Use pypsa_dispatch for hourly fixed-capacity dispatch, cyclic SOC and directional links. MW/MWh; not AC voltage."},
    "opendss": {"title": "OpenDSS", "packages": ["opendssdirect.py>=0.9,<1"],
                "modules": ["opendssdirect"], "tools": ["opendss_feeder"],
                "prompt": "Use opendss_feeder for a balanced three-phase radial feeder snapshot. Line-line kV, total kW/kvar, ohm/km. No arbitrary DSS commands."},
    "pybamm": {"title": "PyBaMM", "packages": ["pybamm>=25.10,<27"],
               "modules": ["pybamm"], "tools": ["battery_discharge"],
               "prompt": "Use battery_discharge for constant-current lithium-ion SPM or DFN. Chen2020 reference cell, A, s and initial SOC. Cutoff can end the run early."},
}
BOOT = ("import sys,runpy; sys.path.insert(0,sys.argv.pop(1)); "
        "runpy.run_module(sys.argv.pop(1),run_name='__main__')")
PROBE = ("import sys,importlib,json; sys.path.insert(0,sys.argv.pop(1)); "
         "print(json.dumps({n:getattr(importlib.import_module(n),'__version__','unknown') "
         "for n in sys.argv[1:]}))")


def plugin_root():
    override = os.environ.get("GRIDAGENT_PLUGIN_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share")
    return (base / "GridAgent" / "plugins").resolve()


def spec(plugin):
    if plugin not in CATALOG:
        raise ValueError("Unknown first-party plugin")
    return CATALOG[plugin]


def clean_env():
    allowed = {"PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "WINDIR", "TEMP", "TMP",
               "LOCALAPPDATA", "APPDATA", "LANG", "LC_ALL", "LD_LIBRARY_PATH",
               "PROCESSOR_ARCHITECTURE", "PROCESSOR_ARCHITEW6432", "PROCESSOR_IDENTIFIER",
               "NUMBER_OF_PROCESSORS", "COMSPEC", "PATHEXT"}
    env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    env.update({"PYTHONNOUSERSITE": "1", "OMP_NUM_THREADS": "1",
                "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                "PYBAMM_DISABLE_TELEMETRY": "true", "PIP_NO_INPUT": "1"})
    return env


def _generation(folder, identifier):
    if identifier == "base":
        return folder
    if not isinstance(identifier, str) or not re.fullmatch(r"[a-f0-9]{32}", identifier):
        raise ValueError("Invalid plugin generation")
    path = folder / (".version-" + identifier)
    if path.is_symlink() or path.resolve().parent != folder:
        raise ValueError("Invalid plugin generation directory")
    return path


def _active(folder):
    try:
        return json.loads((folder / "active.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"current": "base", "previous": None}


def _activate(folder, current, previous):
    stage = folder / (".active-" + uuid4().hex)
    try:
        stage.write_text(json.dumps({"current": current, "previous": previous}), encoding="utf-8")
        stage.replace(folder / "active.json")
    finally:
        stage.unlink(missing_ok=True)


def _installed(plugin, identifier=None):
    spec(plugin)
    root = plugin_root()
    folder = root / plugin
    if folder.resolve().parent != root or folder.is_symlink():
        return None
    try:
        generation = _generation(folder, identifier or _active(folder)["current"])
        data = json.loads((generation / "installed.json").read_text(encoding="utf-8"))
        target = (generation / "packages").resolve()
        if (data["plugin"] == plugin and data["python"] == list(sys.version_info[:2])
                and data["requirements"] == spec(plugin)["packages"]
                and target.parent == generation and target.is_dir()):
            return target, data
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def installed_target(plugin):
    entry = _installed(plugin)
    return entry[0] if entry else None


def installed_metadata(plugin):
    entry = _installed(plugin)
    return entry[1] if entry else {}


def available(plugin):
    return installed_target(plugin) is not None or all(
        importlib.util.find_spec(name) is not None for name in spec(plugin)["modules"])


def status():
    rows = []
    for key, row in CATALOG.items():
        metadata = installed_metadata(key)
        previous = _active(plugin_root() / key)["previous"] if metadata else None
        folder = plugin_root() / key
        rows.append({"id": key, "title": row["title"], "requirements": row["packages"],
                     "installed": available(key), "managed": folder.is_dir() and not folder.is_symlink(), "tools": row["tools"],
                     "versions": metadata.get("versions", {}), "rollback_available": previous is not None})
    return rows


def guidance():
    return "\n".join(row["prompt"] for key, row in CATALOG.items() if available(key))


def install(plugin, *, update=False):
    row = spec(plugin)
    root = plugin_root()
    root.mkdir(parents=True, exist_ok=True)
    with FileLock(str(root / (plugin + ".lock")), timeout=0):
        entry = _installed(plugin)
        if entry is not None and not update:
            return "Already installed"
        folder = root / plugin
        if update and entry is None:
            raise ValueError("Updates require a managed plugin installation")
        if not update and folder.exists():
            raise ValueError("Existing incompatible installation; remove it first")
        stage = root / (".stage-" + uuid4().hex)
        stage.mkdir()
        target = stage / "packages"
        try:
            with (stage / "install.log").open("w", encoding="utf-8") as log:
                subprocess.run([sys.executable, "-I", "-m", "pip", "--isolated", "install",
                                "--disable-pip-version-check", "--no-input", "--only-binary=:all:",
                                "--ignore-installed", "--index-url", "https://pypi.org/simple",
                                "--target", str(target), *row["packages"]],
                               env=clean_env(), cwd=stage, stdout=log, stderr=subprocess.STDOUT,
                               check=True, timeout=1200)
            probe = subprocess.run([sys.executable, "-I", "-c", PROBE, str(target), *row["modules"]],
                                   env=clean_env(), cwd=stage, capture_output=True,
                                   text=True, encoding="utf-8", errors="replace", check=True, timeout=180)
            versions = json.loads(probe.stdout.splitlines()[-1])
            resolved = sorted((d.metadata["Name"], d.version) for d in distributions(path=[str(target)]))
            (stage / "installed.json").write_text(json.dumps({
                "plugin": plugin, "python": list(sys.version_info[:2]), "requirements": row["packages"],
                "versions": versions, "resolved": resolved}, indent=2), encoding="utf-8")
            if update:
                if entry[1].get("resolved") == [list(pair) for pair in resolved]:
                    return "Already at the currently resolved versions"
                previous = _active(folder)["current"]
                generation = uuid4().hex
                stage.rename(_generation(folder, generation))
                _activate(folder, generation, previous)
                return "Updated and import-checked; previous version retained"
            stage.rename(folder)
        except (OSError, subprocess.SubprocessError, ValueError, IndexError, KeyError, TypeError) as exc:
            if (stage / "install.log").is_file():
                shutil.copyfile(stage / "install.log", root / (plugin + "-last-install.log"))
            raise ValueError("Plugin install or import check failed; see local plugin install log") from exc
        finally:
            if stage.exists():
                shutil.rmtree(stage)
    return "Installed and import-checked"


def rollback(plugin):
    spec(plugin)
    root = plugin_root()
    with FileLock(str(root / (plugin + ".lock")), timeout=0):
        if _installed(plugin) is None:
            raise ValueError("Rollback requires a managed plugin installation")
        folder = root / plugin
        active = _active(folder)
        previous = active["previous"]
        if previous is None or _installed(plugin, previous) is None:
            raise ValueError("No compatible previous installation is available")
        _activate(folder, previous, active["current"])
    return "Restored the previous plugin generation"


def updates(plugin):
    from tempfile import TemporaryDirectory

    metadata = installed_metadata(plugin)
    if not metadata:
        raise ValueError("Update checks require a managed plugin installation")
    requirements = spec(plugin)["packages"]
    with TemporaryDirectory(prefix="gridagent-plugin-update-") as tmp:
        report = Path(tmp) / "report.json"
        try:
            subprocess.run([sys.executable, "-I", "-m", "pip", "--isolated", "install", "--dry-run",
                            "--report", str(report), "--disable-pip-version-check", "--no-input", "--only-binary=:all:",
                            "--ignore-installed", "--index-url", "https://pypi.org/simple", *requirements],
                           env=clean_env(), cwd=tmp, capture_output=True, timeout=180, check=True)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError("Could not resolve compatible plugin updates") from exc
        resolved = json.loads(report.read_text(encoding="utf-8"))["install"]
    def canonical(name):
        return re.sub(r"[-_.]+", "-", name.casefold())

    installed = {canonical(name): version for name, version in metadata.get("resolved", [])}
    changes = {}
    for row in resolved:
        if not row.get("requested"):
            continue
        name, version = row["metadata"]["name"], row["metadata"]["version"]
        previous = installed.get(canonical(name))
        if previous != version:
            changes[name] = {"installed": previous, "available": version}
    return changes


def uninstall(plugin):
    spec(plugin)
    root = plugin_root()
    root.mkdir(parents=True, exist_ok=True)
    with FileLock(str(root / (plugin + ".lock")), timeout=0):
        folder = root / plugin
        if folder.resolve().parent != root or folder.is_symlink():
            raise ValueError("Invalid plugin directory")
        if folder.is_dir():
            shutil.rmtree(folder)
            return "Removed managed plugin"
    return "No managed plugin installed"


def launch(plugin, module, folder, timeout=300):
    """Hold a lock while running. No user-supplied module name or arbitrary code."""
    spec(plugin)
    if module not in {"gridagent.native_worker", "gridagent.extension_worker"}:
        raise ValueError("Unsupported plugin worker")
    root = plugin_root()
    root.mkdir(parents=True, exist_ok=True)
    with FileLock(str(root / (plugin + ".lock")), timeout=0):
        target = installed_target(plugin)
        if target is not None:
            args = [sys.executable, "-I", "-B", "-c", BOOT, str(target), module]
        elif available(plugin):
            args = [sys.executable, "-I", "-B", "-m", module]
        else:
            raise ValueError("Plugin not installed; use the user-controlled plugin manager")
        with (folder / "solver.log").open("w", encoding="utf-8") as log:
            return subprocess.run(args, cwd=folder, env=clean_env(), stdout=log,
                                  stderr=subprocess.STDOUT, timeout=timeout, check=False)
