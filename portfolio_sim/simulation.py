import numpy as np

from .imports import InputError


def simulate(returns, values, years=10, paths=2000, seed=42):
    for label, value, low, high in [("Years", years, 1, 30), ("Paths", paths, 100, 5000), ("Seed", seed, 0, 2**32 - 1)]:
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise InputError(f"{label} must be an integer between {low} and {high}.")
    r, values = np.asarray(returns, dtype=float), np.asarray(values, dtype=float)
    if r.ndim != 2 or r.shape[0] < 24 or not 1 <= r.shape[1] <= 50 or values.shape != (r.shape[1],):
        raise InputError("Insufficient or mismatched portfolio history.")
    if not np.isfinite(r).all() or not np.isfinite(values).all() or (values <= 0).any():
        raise InputError("Portfolio inputs must be finite and values positive.")
    steps, n = years * 12, len(values)
    if paths * steps * n > 60_000_000:
        raise InputError("Reduce the years or simulation count for this many holdings (maximum 60 million asset-months).")
    drift = r.mean(axis=0)
    cov = np.atleast_2d(np.cov(r, rowvar=False, ddof=1))
    eigenvalues, eigenvectors = np.linalg.eigh(cov)

    root = eigenvectors @ np.diag(np.sqrt(np.maximum(eigenvalues, 0)))
    rng = np.random.default_rng(seed)
    total = np.empty((paths, steps + 1))
    total[:, 0] = values.sum()
    log_growth = np.zeros((paths, n))
    for month in range(1, steps + 1):

        log_growth += drift + rng.standard_normal((paths, n)) @ root.T
        if np.max(log_growth) > 600:
            raise InputError("The fitted history produces unstable projections; use a different portfolio or shorter horizon.")
        total[:, month] = np.exp(log_growth) @ values
    if not np.isfinite(total).all():
        raise InputError("The simulation exceeded numerical limits.")
    bands = np.percentile(total, [5, 25, 50, 75, 95], axis=0)
    end = total[:, -1]


    histogram_range = None
    if np.ptp(end) < max(1e-8, abs(float(np.median(end))) * 1e-10):
        center = float(np.median(end))
        half_width = max(.5, abs(center) * .005)
        histogram_range = (center - half_width, center + half_width)
    counts, edges = np.histogram(end, bins=40, range=histogram_range)
    return {"time": (np.arange(steps + 1) / 12).tolist(), "bands": {str(p): bands[i].tolist() for i, p in enumerate([5, 25, 50, 75, 95])}, "sample_paths": total[:min(25, paths)].tolist(), "initial": float(values.sum()), "median": float(np.median(end)), "p05": float(np.percentile(end, 5)), "p95": float(np.percentile(end, 95)), "loss_probability": float(np.mean(end < values.sum())), "histogram": {"centers": ((edges[1:] + edges[:-1]) / 2).tolist(), "widths": np.diff(edges).tolist(), "counts": counts.tolist()}, "years": years, "paths": paths, "seed": seed}
