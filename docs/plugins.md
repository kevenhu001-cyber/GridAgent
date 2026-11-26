# First-party solver plugins

Core includes ANDES, pandapower, HiGHS, Python Control, NumPy/SciPy,
pandas, SymPy, NetworkX, CPython 3.11 and pip. PyPSA is not bundled.
The original paper assets and research results remain in their separate locations.

The native Simulation Plugins window shows the first-party catalog. Click Install,
then approve the package names and source. The explicit CLI and TUI commands are:
    
    gridagent --plugins
    gridagent --plugin-install pypsa
    gridagent --plugin-install opendss
    gridagent --plugin-install pybamm
    gridagent --plugin-install pvlib
    gridagent --plugin-remove pypsa

The Agent never installs packages itself. A missing backend is shown by
list_simulation_backends; use the plugin window, then ask in the same session again.
Every chat turn binds installed plugin tools and matching curated guidance; their
schemas also enter the engineering knowledge index. Uninstall removes managed
packages, not experiment files or Core. Packages already present in a developer
environment remain available and are not removed by the manager.

Installation uses the bundled pip, a first-party allowlist, HTTPS PyPI, binary
wheels only and a staging directory. Import probe precedes atomic directory
publication. Resolved distribution versions are recorded. Each plugin has its own
package directory under the user data folder; environment variables carrying
model provider keys are omitted. Numerical tools run in short-lived child
processes with a per-plugin lock. This is dependency/process isolation, NOT an
OS security sandbox. Wheels are executable third-party code. The current
version ranges are not a cryptographically pinned wheel lock. Managed
environments use independent copies of dependencies, with pip download caching;
there is no shared installed-file deduplication yet.

PyPSA retains the native independent quality evaluator and modeling benchmarks.
OpenDSS exposes a balanced two-bus feeder snapshot, not the entire DSS language.
PyBaMM exposes Chen2020 reference-cell SPM/DFN constant-current discharge, not a
calibrated model of every chemistry. The latter two save numeric CSV output
and check solver success/finite results; independent physical benchmark suites
are future work. pvlib exposes PVWatts DC power with explicit irradiance and cell temperature.
Core Python Control exposes typed SISO step response and poles. These tools
have analytic reference regression tests but not full modeling benchmarks.

Other open-source or commercial platforms require their own reviewed adapter,
manifest, prompts and evaluation. No arbitrary remote MCP servers, package names,
or unreviewed installation scripts are accepted. PowerMCP integration, upgrades,
offline wheel bundles, and task auto-resume are future work.

The built-in catalog also includes windpowerlib (user-supplied turbine power curves),
CVXPY (convex quadratic economic dispatch), Pyomo/HiGHS (bounded hourly single-bus
unit commitment), and CasADi (first-order Thevenin RC battery dynamics). Each has
a typed tool, curated prompt, bounded result tables and analytic smoke-test reference.
There is no plugin marketplace, account, or remote manifest infrastructure.
