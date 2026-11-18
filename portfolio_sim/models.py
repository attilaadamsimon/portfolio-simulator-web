"""Additional portfolio models; monthly summaries keep large runs memory bounded."""
import math
import numpy as np

from .imports import InputError

MODEL_NAMES = {'gbm': 'GBM', 'merton': 'Merton jump-diffusion', 'heston': 'Heston', 'bootstrap': 'Historical bootstrap'}
DEFAULTS = {'jump_frequency': .5, 'jump_mean': -.15, 'jump_std': .10,
            'kappa': 2., 'theta_vol': .20, 'xi': .30, 'rho': -.6, 'block_months': 1}
LIMITS = {'drift': (-.8, .4), 'volatility': (0, 1), 'jump_frequency': (0, 10),
          'jump_mean': (-.8, .8), 'jump_std': (0, 1), 'kappa': (.1, 10),
          'theta_vol': (0, 1), 'xi': (0, 2), 'rho': (-.95, .95), 'block_months': (1, 12)}


class Cancelled(Exception):
    """A newer request or the Cancel button stopped this run."""


def validate_options(options):
    if not isinstance(options, dict):
        raise InputError('Provide model settings as an object.')
    model = options.get('model', 'gbm')
    if not isinstance(model, str) or model not in MODEL_NAMES:
        raise InputError('Choose GBM, Merton, Heston or historical bootstrap.')
    out = dict(DEFAULTS, model=model, drift=None, volatility=None)
    for key, (low, high) in LIMITS.items():
        value = options.get(key, out.get(key))
        if value is None and key in {'drift', 'volatility'}:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise InputError(f'{key} must be between {low} and {high}.')
        if key == 'block_months' and not isinstance(value, int):
            raise InputError('Bootstrap block length must be a whole number of months.')
        out[key] = value
    return out


def calibration(returns, values):
    r = np.asarray(returns, dtype=float)
    w = np.asarray(values, dtype=float) / np.sum(values)
    cov = np.atleast_2d(np.cov(r, rowvar=False, ddof=1))
    return {'drift': float(r.mean(axis=0) @ w * 12),
            'volatility': float(np.sqrt(max(0, w @ cov @ w) * 12))}


def simulate_model(returns, values, years=10, paths=2000, seed=42, options=None,
                   progress=None, cancelled=None, historical=None):
    options = validate_options(options or {})
    for label, value, low, high in [('Years', years, 1, 30), ('Paths', paths, 100, 200000), ('Seed', seed, 0, 2**32-1)]:
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise InputError(f'{label} must be an integer between {low} and {high}.')
    r, values = np.asarray(returns, dtype=float), np.asarray(values, dtype=float)
    if r.ndim != 2 or r.shape[0] < 24 or not 1 <= r.shape[1] <= 50 or values.shape != (r.shape[1],):
        raise InputError('Insufficient or mismatched portfolio history.')
    if not np.isfinite(r).all() or not np.isfinite(values).all() or (values <= 0).any():
        raise InputError('Portfolio inputs must be finite and values positive.')
    model = options['model']
    steps, n = years * 12, len(values)
    substeps = 4 if model == 'heston' else 1
    if paths * steps * n * substeps > 1_000_000_000:
        raise InputError('This combination is too large. Reduce paths, years or holdings (Heston uses four steps per month).')
    mean = r.mean(axis=0)
    cov = np.atleast_2d(np.cov(r, rowvar=False, ddof=1))
    weights = values / values.sum()
    original_mean = mean.copy()
    scale = 1.
    if options['drift'] is not None:
        # Shift every asset equally, keeping relative historical drift differences.
        mean = mean + options['drift'] / 12 - mean @ weights
    if options['volatility'] is not None:
        current = np.sqrt(max(0, weights @ cov @ weights) * 12)
        if current > 1e-12:
            scale = options['volatility'] / current
            cov = cov * scale**2
        elif options['volatility'] > 0:
            raise InputError('This history has no portfolio variation to scale. Use historical volatility or another portfolio.')
        else:
            scale = 0.
            cov = np.zeros_like(cov)
    eigenvalues, eigenvectors = np.linalg.eigh(cov)
    root = eigenvectors @ np.diag(np.sqrt(np.maximum(eigenvalues, 0)))
    rng = np.random.default_rng(seed)
    initial = float(values.sum())
    log_growth = np.zeros((paths, n))
    samples = np.empty((min(25, paths), steps + 1)); samples[:, 0] = initial
    bands = np.empty((5, steps + 1)); bands[:, 0] = initial
    adjusted_history = r if options["drift"] is None and options["volatility"] is None else (r - original_mean) * scale + mean
    annual_var = np.maximum(np.diag(cov) * 12, 0)
    variance = np.broadcast_to(annual_var, (paths, n)).copy() if model == 'heston' else None
    if model == 'heston':
        std = np.sqrt(np.maximum(np.diag(cov), 0))
        corr = np.divide(cov, np.outer(std, std), out=np.zeros_like(cov), where=np.outer(std, std) > 1e-20)
        np.fill_diagonal(corr, 1.)
        ev, evec = np.linalg.eigh(corr)
        corr_root = evec @ np.diag(np.sqrt(np.maximum(ev, 0)))
        port_vol = np.sqrt(max(0, weights @ cov @ weights) * 12)
        theta = annual_var * (options['theta_vol'] / port_vol)**2 if port_vol > 1e-12 else np.full(n, options['theta_vol']**2 / (weights @ weights))
    end = np.full(paths, initial)
    for month in range(1, steps + 1):
        if cancelled and cancelled():
            raise Cancelled()
        if model in {'gbm', 'merton'}:
            # Same draw order and log drift as the original GBM implementation.
            log_growth += mean + rng.standard_normal((paths, n)) @ root.T
            if model == 'merton' and options['jump_frequency']:
                count = rng.poisson(options['jump_frequency'] / 12, size=paths)
                jump = count * options['jump_mean'] + np.sqrt(count) * options['jump_std'] * rng.standard_normal(paths)
                # Standard Merton compensation preserves the diffusion's arithmetic expectation.
                compensation = options['jump_frequency'] * np.expm1(options['jump_mean'] + .5 * options['jump_std']**2) / 12
                log_growth += (jump - compensation)[:, None]
        elif model == 'bootstrap':
            block = options['block_months']
            if (month - 1) % block == 0:
                indices = rng.integers(0, len(r), size=paths)
            # Entire rows are resampled together; circular blocks retain short serial patterns.
            log_growth += adjusted_history[indices]
            indices = (indices + 1) % len(r)
        else:
            dt = 1 / 48
            for _ in range(4):
                if cancelled and cancelled():
                    raise Cancelled()
                v = np.maximum(variance, 0)
                z = rng.standard_normal((paths, n)) @ corr_root.T
                zv = options['rho'] * z + np.sqrt(1-options['rho']**2) * rng.standard_normal((paths, n))
                # Full-truncation Euler: negative internal variance is never square-rooted.
                log_growth += (mean * 12 + .5 * annual_var - .5 * v) * dt + np.sqrt(v * dt) * z
                variance += options['kappa'] * (theta - v) * dt + options['xi'] * np.sqrt(v * dt) * zv
        if not np.isfinite(log_growth).all() or np.max(log_growth) > 600:
            raise InputError('These settings produce unstable projections. Reduce volatility, jump size or the horizon.')
        end = np.exp(log_growth) @ values
        if not np.isfinite(end).all():
            raise InputError('The simulation exceeded numerical limits.')
        # Store only monthly quantiles and 25 display paths, not all full paths.
        bands[:, month] = np.percentile(end, [5, 25, 50, 75, 95])
        samples[:, month] = end[:len(samples)]
        if progress:
            progress(month / steps)
    histogram_range = None
    if np.ptp(end) < max(1e-8, abs(float(np.median(end))) * 1e-10):
        center = float(np.median(end)); half_width = max(.5, abs(center) * .005)
        histogram_range = (center-half_width, center+half_width)
    counts, edges = np.histogram(end, bins=40, range=histogram_range)
    result = {'time': (np.arange(steps+1)/12).tolist(), 'bands': {str(p): bands[i].tolist() for i,p in enumerate([5,25,50,75,95])},
              'sample_paths': samples.tolist(), 'initial': initial, 'median': float(np.median(end)),
              'p05': float(np.percentile(end,5)), 'p95': float(np.percentile(end,95)),
              'loss_probability': float(np.mean(end < initial)),
              'histogram': {'centers': ((edges[1:]+edges[:-1])/2).tolist(), 'widths': np.diff(edges).tolist(), 'counts': counts.tolist()},
              'years': years, 'paths': paths, 'seed': seed, 'model': model, 'model_name': MODEL_NAMES[model], 'parameters': options}
    if historical is not None:
        actual = np.asarray(historical, dtype=float)
        if actual.shape != (steps+1,) or not np.isfinite(actual).all():
            raise InputError('Historical comparison must match the simulation horizon.')
        outside = (actual[1:] < bands[0,1:]) | (actual[1:] > bands[4,1:])
        # Midrank handles deterministic ties instead of incorrectly calling them 100th percentile.
        percentile = 100 * (np.mean(end < actual[-1]) + .5*np.mean(end == actual[-1]))
        result['historical'] = {'values': actual.tolist(), 'percentile': float(percentile),
                                'outside_months': int(outside.sum()), 'months': steps, 'inside': (~outside).tolist()}
    return result
