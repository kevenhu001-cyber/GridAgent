"""First-party opt-in solver extensions. No executable third-party manifests."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from filelock import FileLock

CATALOG = {
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


def installed_target(plugin):
    spec(plugin)
    root = plugin_root()
    folder = root / plugin
    if folder.resolve().parent != root or folder.is_symlink():
        return None
    try:
        data = json.loads((folder / "installed.json").read_text(encoding="utf-8"))
        target = (folder / "packages").resolve()
        if (data["plugin"] == plugin and data["python"] == list(sys.version_info[:2])
                and data["requirements"] == spec(plugin)["packages"]
                and target.parent == folder and target.is_dir()):
            return target
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def available(plugin):
    return installed_target(plugin) is not None or all(
        importlib.util.find_spec(name) is not None for name in spec(plugin)["modules"])


def status():
    return [{"id": key, "title": row["title"], "requirements": row["packages"],
             "installed": available(key), "managed": installed_target(key) is not None,
             "tools": row["tools"]} for key, row in CATALOG.items()]


def guidance():
    return "\n".join(row["prompt"] for key, row in CATALOG.items() if available(key))


def install(plugin):
    row = spec(plugin)
    root = plugin_root()
    root.mkdir(parents=True, exist_ok=True)
    with FileLock(str(root / (plugin + ".lock")), timeout=0):
        if installed_target(plugin) is not None:
            return "Already installed"
        folder = root / plugin
        if folder.exists():
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
            from importlib.metadata import distributions

            resolved = sorted((d.metadata["Name"], d.version) for d in distributions(path=[str(target)]))
            (stage / "installed.json").write_text(json.dumps({
                "plugin": plugin, "python": list(sys.version_info[:2]), "requirements": row["packages"],
                "versions": versions, "resolved": resolved}, indent=2), encoding="utf-8")
            stage.rename(folder)
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            if (stage / "install.log").is_file():
                shutil.copyfile(stage / "install.log", root / (plugin + "-last-install.log"))
            raise ValueError("Plugin install or import check failed; see local plugin install log") from exc
        finally:
            if stage.exists():
                shutil.rmtree(stage)
    return "Installed and import-checked"


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
