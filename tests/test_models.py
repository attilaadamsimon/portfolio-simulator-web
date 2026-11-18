import numpy as np
import pytest
from portfolio_sim.imports import InputError
from portfolio_sim.simulation import simulate
from portfolio_sim.models import simulate_model, Cancelled
from portfolio_sim.experiments import backtest_inputs, run_experiment

@pytest.fixture
def history():
    return np.random.default_rng(12).normal([.004,.006],[.03,.05],(60,2))

@pytest.mark.parametrize('seed',[0,42,999])
def test_gbm_matches_existing_engine_exactly(history,seed):
    old=simulate(history,[200,800],years=2,paths=500,seed=seed)
    new=simulate_model(history,[200,800],years=2,paths=500,seed=seed)
    assert {k:new[k] for k in old} == old

@pytest.mark.parametrize('model',['gbm','merton','heston','bootstrap'])
def test_models_repeat_and_have_valid_bands(history,model):
    a=simulate_model(history,[200,800],years=1,paths=300,options={'model':model})
    assert a == simulate_model(history,[200,800],years=1,paths=300,options={'model':model})
    assert np.all(np.diff(np.array(list(a['bands'].values())),axis=0)>=0)
    assert sum(a['histogram']['counts'])==300
    assert np.isfinite(a['sample_paths']).all()

def test_zero_jump_rate_is_exact_gbm(history):
    a=simulate_model(history,[200,800],years=1,paths=100)
    b=simulate_model(history,[200,800],years=1,paths=100,options={'model':'merton','jump_frequency':0})
    assert a['bands']==b['bands']

def test_bootstrap_samples_whole_rows():
    r=np.tile([[.01,-.01],[.02,-.02]],(20,1))
    out=simulate_model(r,[100,100],years=1,paths=100,options={'model':'bootstrap'})
    assert np.min(out['sample_paths'])>=200

def test_override_deterministic_growth(history):
    out=simulate_model(history,[200,800],years=1,paths=100,options={'drift':.06,'volatility':0})
    assert out['p05']==out['p95']

def test_cancellation(history):
    with pytest.raises(Cancelled):
        simulate_model(history,[200,800],cancelled=lambda:True)

def test_backtest_uses_no_test_returns_in_fit(history):
    fit,actual=backtest_inputs(history,[200,800])
    changed=history.copy();changed[-12:]+=.2
    other,other_actual=backtest_inputs(changed,[200,800])
    assert np.array_equal(fit,other)
    assert other_actual[-1]>actual[-1]
    assert actual[0]==1000

def test_backtest_requires_training_history(history):
    with pytest.raises(InputError,match='36'):
        backtest_inputs(history[:35],[200,800])

def test_compare_matches_single_model(history):
    prep={'returns':history,'values':np.array([200,800]),'demo':True,'warnings':[]}
    multi=run_experiment(prep,{'years':1,'paths':100,'models':['gbm','merton']})
    single=run_experiment(prep,{'years':1,'paths':100,'models':['merton']})
    assert multi['comparisons'][1]['bands']==single['bands']

def test_stress_overrides_custom_parameters(history):
    prep={'returns':history,'values':np.array([200,800]),'demo':True,'warnings':[]}
    out=run_experiment(prep,{'years':1,'paths':100,'scenario':'crisis2008','parameters':{'drift':.3}})
    assert out['parameters']['drift']==-.45

@pytest.mark.parametrize('options',[{'rho':float('nan')},{'model':[]},{'block_months':1.5},{'jump_std':-1}])
def test_model_validation(history,options):
    with pytest.raises(InputError):simulate_model(history,[200,800],options=options)

def test_backtest_final_percentile_and_ties():
    r=np.zeros((48,1))
    out=simulate_model(r,[100],years=1,paths=100,historical=np.full(13,100.))
    assert out['historical']['percentile']==50
    assert out['historical']['outside_months']==0

def test_backtest_rejects_calendar_gaps(history):
    import pandas as pd
    dates=pd.date_range('2020-01-31',periods=61,freq='ME').delete(20)
    with pytest.raises(InputError,match='uninterrupted'):
        backtest_inputs(pd.DataFrame(history,index=dates),[200,800])

def test_held_out_data_does_not_change_simulated_bands(history):
    import pandas as pd
    def run(r):
        p={'returns':pd.DataFrame(r,index=pd.date_range('2020-01-31',periods=60,freq='ME')),
           'values':np.array([200,800]),'demo':False,'warnings':[]}
        return run_experiment(p,{'paths':100,'backtest':True})
    other=history.copy();other[-12:]+=.1
    a,b=run(history),run(other)
    assert a['bands']==b['bands']
    assert a['historical']['values']!=b['historical']['values']
    assert a['backtest_info']['train_end'] < a['backtest_info']['test_start']

def test_heston_with_constant_variance_matches_gbm_distribution():
    r=np.tile([-.04,.04],30).reshape(-1,1)
    vol=float(np.std(r,ddof=1)*np.sqrt(12))
    g=simulate_model(r,[100],years=1,paths=10000)
    h=simulate_model(r,[100],years=1,paths=10000,options={'model':'heston','xi':0,'theta_vol':vol})
    assert h['median']==pytest.approx(g['median'],rel=.02)
    assert h['p95']==pytest.approx(g['p95'],rel=.03)

def test_merton_compensation_preserves_expected_price():
    r=np.zeros((36,1))
    out=simulate_model(r,[100],years=1,paths=50000,options={'model':'merton','jump_frequency':2,'jump_mean':-.2,'jump_std':0})
    # The histogram approximation is sufficient to detect missing/wrong compensation.
    h=out['histogram']
    approximate_mean=np.average(h['centers'],weights=h['counts'])
    assert approximate_mean==pytest.approx(100,rel=.03)

def test_large_path_count_stays_compact(history):
    out=simulate_model(history,[200,800],years=1,paths=100000)
    assert len(out['sample_paths'])==25
    assert sum(out['histogram']['counts'])==100000
    assert len(out['bands']['50'])==13

def test_cancellation_after_progress(history):
    fractions=[]
    with pytest.raises(Cancelled):
        simulate_model(history,[200,800],progress=fractions.append,cancelled=lambda:bool(fractions))
    assert len(fractions)==1
