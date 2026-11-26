# Verified research tasks

## Configure a model

In the native Windows app, open **Workspace and model settings**, enter the
model ID and OpenAI-compatible base URL, and select **Test connection**. A
connection test sends a short prompt to the selected endpoint. **Save model**
stores the model ID and URL in the selected workspace. The API key stays in
the running client. In the TUI, open the same settings with `/model` or
`Ctrl+P`. CLI commands use the saved settings, with
`GRIDAGENT_MODEL` and `GRIDAGENT_BASE_URL` taking precedence. Set
`GRIDAGENT_API_KEY` in the CLI process environment to authenticate.

## Run and recover a task

Use **Run research task** in Windows, `/research QUESTION` in the TUI, or
`gridagent --research "QUESTION"` in the CLI. Select **Open manifest** in the
Windows Tasks tab to start the typed workflow. CLI and TUI can run it from a
trusted JSON manifest without a model key when the base case passes:

```text
gridagent --research-manifest examples/power-flow-research.json
gridagent --research-tasks
gridagent --research-status TASK_ID
gridagent --research-clarify TASK_ID "The low-voltage side is 20 kV."
gridagent --research-approve TASK_ID
gridagent --research-resume TASK_ID
gridagent --research-cancel TASK_ID
gridagent --research-report TASK_ID report.json
```

The TUI equivalents use `/research-manifest`, `/research-resume` and the other
commands without the CLI dashes. Press `Ctrl+X` to cancel the active task.
The Windows Tasks tab exposes the same controls. To submit a clarification in
Windows, enter it in the prompt box and select **Use prompt as answer**.

The engine records the input hash, authorized repair ranges, scenario
requirements, solver version and budgets in SQLite. Scenarios can scale all
loads or apply one in-service line or transformer outage. The native worker
accepts validated two-winding transformers and bus, line and transformer
switches. The deterministic evaluator checks scenario fidelity, finite
in-service bus results, power balance and voltage and loading thresholds.
Completed runs can be recovered by their run ID. An unresolved reservation
consumes budget and is recorded as unknown.

Single Agent mode is the default. Multi Agent mode adds a specialist retrieval
step before modeling and uses the same numerical executor and diagnosis and
repair flow. Simulations are independent of the proposing model. Verified
local repairs record matching scenarios, failed checks, repair directions and
provenance. A later task logs whether a proposal used those hints and how the
candidate scored. View these records with `--research-experience`.

## Python, external runtimes and the workbench

Enable workspace automatic execution with **Automatic Python settings** or
`--research-sandbox enable`. Then run **Run verified Python** or
`--research-python MANIFEST`. The engine generates and retries Python in
Windows Sandbox, and compares the returned bus voltages, angles and P/Q
against an independently evaluated native reference. The budget counts both
reference runs and script attempts. This requires the Windows Sandbox CLI and
the packaged embedded interpreter. The workflow records source hashes and
script results under the study ID.

```text
gridagent --register-ngspice PATH_TO_CONSOLE_EXE
gridagent --ngspice-rc transient 1000 0.000001
gridagent --ngspice-rc ac 1000 0.000001
gridagent --andes-batch BATCH.json
gridagent --plugin-check PLUGIN
gridagent --plugin-update PLUGIN
gridagent --plugin-rollback PLUGIN
```

The ngspice adapter checks the executable fingerprint and verifies the RC
response against its analytic solution. The ANDES batch accepts `faults`,
`governor_eigen` and `governor_faults` arrays. A governor request identifies an
active TGOV1 device and a bounded `R` or `T1` value. PyPSA dispatch accepts
passive `lines` with `bus0`, `bus1`, `s_nom_mva` and `x_ohm`.
The Windows Runs tab can open a pandapower topology, save a parameter revision,
overlay voltage waveforms, and display eigenvalue, Bode and root-locus charts
from supported runs. Open a saved model revision in **Models** and run it to
reproduce that version.

The knowledge index includes versioned summaries linked to official
pandapower, ANDES and PyPSA sections. To add local semantic retrieval, install
the `retrieval` extra separately and point `GRIDAGENT_EMBEDDINGS_PATH` at a
local multilingual E5 model directory. Keyword and API-dependency retrieval are
available in the standard runtime.

## Public benchmarks and comparisons

```text
gridagent --research-benchmark
gridagent --research-benchmark all reference
gridagent --research-benchmark transformer-1 multi
gridagent --research-compare transformer-1 10 MODEL_A MODEL_B
gridagent --research-experience training-snapshot.json
gridagent --research-compare transformer-1 10 MODEL_A MODEL_B memory training-snapshot.json
```

The public AC suite contains 20 cases in five families, each with base and peak
loads. The reference mode verifies native bus voltages against a closed-form
solution. Comparison trials use the same scenario budget for single Agent,
multi Agent, repair disabled and experience disabled. They record first and
final pass rates, simulation and repair counts, wall time, reported token
usage and failure categories. Run the optional training snapshot from a
separate workspace. The comparison stores scored runs in a fresh workspace and
uses the snapshot only for historical repair directions.
Choose `modeling/TASK` or `repair/TASK` to run only one track.

The public cases establish a development baseline. The proposed 200-task
cross-domain suite and private model-family holdout require additional
evaluators and data. Licensed simulator validation is tracked separately.
