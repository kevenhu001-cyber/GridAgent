"""Deterministic small-signal mode analysis."""
import numpy as np


def summarize_modes(eigenvalues, tolerance=1e-7):
    values = np.asarray(eigenvalues, dtype=complex).ravel()
    if not values.size or not np.isfinite(values).all():
        raise ValueError("No finite eigenvalues")
    if not np.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("Invalid numerical tolerance")
    rows = []
    for index, value in enumerate(values):
        real, imag = float(value.real), float(value.imag)
        magnitude = abs(value)
        classification = "growing" if real > tolerance else "decaying" if real < -tolerance else "neutral"
        rows.append({"index": index, "real_per_s": real, "imag_rad_s": imag,
                     "frequency_hz": abs(imag) / (2 * np.pi),
                     "damping_ratio": -real / magnitude if magnitude > tolerance else None,
                     "classification": classification})
    positive = sum(row["classification"] == "growing" for row in rows)
    neutral = sum(row["classification"] == "neutral" for row in rows)
    # Neutral modes (including reference-angle symmetry) are not classified as asymptotically stable.
    status = "growing_modes" if positive else "neutral_modes" if neutral else "all_modes_decaying"
    oscillatory = [row for row in rows if row["imag_rad_s"] > tolerance and row["damping_ratio"] is not None]
    oscillatory.sort(key=lambda row: row["damping_ratio"])
    return {"mode_count": len(rows), "growing_count": positive, "neutral_count": neutral,
            "decaying_count": len(rows) - positive - neutral, "classification": status,
            "spectral_abscissa_per_s": float(values.real.max()), "tolerance_per_s": tolerance,
            "least_damped_oscillatory_modes": oscillatory[:10], "modes": rows}
