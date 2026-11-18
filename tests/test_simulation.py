import numpy as np
import pytest

from portfolio_sim.imports import InputError
from portfolio_sim.simulation import simulate


def test_deterministic_growth_is_sum_of_asset_paths_not_rebalanced():
    returns = np.tile([.01, -.005], (36, 1))
    r = simulate(returns, [100, 300], years=2, paths=100)
    expected = 100 * np.exp(.01 * 24) + 300 * np.exp(-.005 * 24)
    assert r['initial'] == 400
    assert r['median'] == pytest.approx(expected)
    assert r['p05'] == pytest.approx(r['p95'])


def test_single_asset_and_reproducibility():
    r = np.random.default_rng(1).normal(.005, .04, (50, 1))
    a = simulate(r, [2000], years=1, paths=500, seed=10)
    b = simulate(r, [2000], years=1, paths=500, seed=10)
    assert a == b
    assert a['p05'] < a['median'] < a['p95']
    assert all(p[0] == 2000 for p in a['sample_paths'])
    assert sum(a['histogram']['counts']) == 500


def test_correlation_affects_portfolio_risk():
    rng = np.random.default_rng(4)
    r = rng.normal(0, .06, 60)
    aligned = simulate(np.column_stack([r,r]), [500,500], years=1, paths=4000)
    hedge = simulate(np.column_stack([r,-r]), [500,500], years=1, paths=4000)
    assert aligned['p95'] - aligned['p05'] > hedge['p95'] - hedge['p05']
    assert hedge['loss_probability'] == 0


def test_log_mean_not_double_corrected():
    r = np.random.default_rng(8).normal(0,.08,(60,1))
    r -= r.mean(axis=0)
    result = simulate(r, [1000], years=1, paths=5000)
    assert result['median'] == pytest.approx(1000, rel=.025)


def test_percentiles_are_ordered_and_start_identically():
    r = np.random.default_rng(6).normal(.004,.03,(48,3))
    out = simulate(r, [100,200,500], years=3, paths=500)
    bands = np.array(list(out['bands'].values()))
    assert np.all(np.diff(bands, axis=0) >= 0)
    assert np.all(bands[:,0] == 800)
    assert 0 <= out['loss_probability'] <= 1


@pytest.mark.parametrize('kwargs', [{'years':0},{'years':1.5},{'paths':True},{'paths':5001},{'seed':-1}])
def test_limits(kwargs):
    with pytest.raises(InputError):
        simulate(np.zeros((36,1)), [100], **kwargs)
