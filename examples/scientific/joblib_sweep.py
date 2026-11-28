"""Guest-side example: independent numerical scenarios with a small thread budget.

Use plugin_ids=["joblib"] if Joblib is not already bundled. Reuse the native
scientific job, not a separate task scheduler. Do not load untrusted pickles.
"""
import json
import os
from pathlib import Path

import numpy as np


def response(resistance):
    # Illustrative RC decay; replace with independent solver cases as needed.
    t = np.linspace(0.0, 1.0, 1001)
    voltage = np.exp(-t / (resistance * 0.1))
    return {"resistance_ohm": resistance, "final_voltage_v": float(voltage[-1])}


def sweep(resistances, workers=2):
    from joblib import Parallel, delayed

    if type(workers) is not int or not 1 <= workers <= 4:
        raise ValueError("Use one to four worker threads")
    if not 1 <= len(resistances) <= 128 or any(
            not np.isfinite(r) or not 0.1 <= r <= 1000 for r in resistances):
        raise ValueError("Use 1–128 finite positive resistances between 0.1 and 1000 ohm")
    # Shared-memory requirement avoids a process pool in the embedded Windows runtime.
    return Parallel(n_jobs=workers, require="sharedmem")(
        delayed(response)(float(r)) for r in resistances)


def main():
    rows = sweep([1.0, 2.0, 5.0, 10.0])
    output = Path(os.environ["GRIDAGENT_OUTPUT_DIR"])
    (output / "parallel-sweep.json").write_text(json.dumps({
        "model": "illustrative RC decay", "rows": rows,
        "verification": "unverified_script_output",
    }, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    main()
