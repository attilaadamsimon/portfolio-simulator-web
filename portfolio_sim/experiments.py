from datetime import datetime, timezone
import numpy as np
import pandas as pd

from .imports import InputError
from .models import MODEL_NAMES, validate_options, simulate_model, calibration, Cancelled
from .scenarios import SCENARIOS


def validate_request(body):
    if not isinstance(body, dict):
        raise InputError('Send valid simulation settings.')
    if not isinstance(body.get('currency','EUR'),str) or not isinstance(body.get('selection','All'),str) or body.get('currency','EUR') not in {'EUR','USD'} or body.get('selection','All') not in {'All','Stock','ETF'}:
        raise InputError('Select EUR/USD and All/Stock/ETF.')
    for key in ('demo','allow_stale','refresh','backtest'):
        if key in body and not isinstance(body[key], bool):
            raise InputError(f'Invalid {key} setting.')
    for key, default, low, high in [('years',10,1,30),('paths',2000,100,200000),('seed',42,0,2**32-1)]:
        value = body.get(key,default)
        if isinstance(value,bool) or not isinstance(value,int) or not low <= value <= high:
            raise InputError(f'{key} must be an integer between {low} and {high}.')
    selected = body.get('models',['gbm'])
    if not isinstance(selected,list) or not 1 <= len(selected) <= 4 or any(not isinstance(m,str) or m not in MODEL_NAMES for m in selected) or len(set(selected)) != len(selected):
        raise InputError('Choose one to four distinct models.')
    validate_options(body.get('parameters',{}))
    if not isinstance(body.get('scenario','normal'),str) or body.get('scenario','normal') not in {'normal',*SCENARIOS}:
        raise InputError('Choose a listed stress scenario or Normal.')


def backtest_inputs(returns, values):
    if len(returns) < 36:
        raise InputError('Not enough history for backtesting: need 36 shared months (24 for fitting, 12 held out). Normal simulation is still available.')
    if isinstance(returns, pd.DataFrame):
        periods = returns.index.to_period('M').asi8
        if np.any(np.diff(periods) != 1):
            raise InputError('Backtesting requires uninterrupted monthly history; these holdings have gaps. Normal simulation is still available.')
    r = np.asarray(returns, dtype=float)

    actual = np.r_[np.sum(values), np.exp(np.cumsum(r[-12:], axis=0)) @ values]
    return r[:-12], actual


def run_experiment(prepared, body, progress=None, cancelled=None):
    validate_request(body)
    data = dict(prepared)
    returns, values = data.pop('returns'), data.pop('values')
    backtest = body.get('backtest',False)
    years = 1 if backtest else body.get('years',10)
    actual = None
    fit_returns = returns
    if backtest:
        fit_returns, actual = backtest_inputs(returns, values)
    parameters = dict(body.get('parameters',{}))
    scenario = body.get('scenario','normal')
    if scenario != 'normal':
        parameters.update({k:v for k,v in SCENARIOS[scenario].items() if k not in {'name','note'}})
    results = []
    models = body.get('models',['gbm'])
    for i, model in enumerate(models):
        if cancelled and cancelled():
            raise Cancelled()
        callback = (lambda p, i=i, model=model: progress((i+p)/len(models), f'{MODEL_NAMES[model]} | {int(p*100)}%')) if progress else None
        result = simulate_model(fit_returns, values, years, body.get('paths',2000), body.get('seed',42),
                                dict(parameters, model=model), callback, cancelled, actual)
        results.append(result)
    result = dict(results[0])
    result.update(data, currency=body.get('currency','EUR'), selection=body.get('selection','All'),
                  calculated_at=datetime.now(timezone.utc).isoformat(), comparisons=results,
                  calibration=calibration(fit_returns,values), scenario=scenario, backtest=backtest)
    result['warnings'] = list(data.get('warnings',[]))
    if scenario != 'normal':
        result['warnings'].append(SCENARIOS[scenario]['note'] + ' These conditions apply throughout the selected horizon; choose Normal to restore your settings.')
    if parameters.get('drift') is not None or parameters.get('volatility') is not None:
        result['warnings'].append('Custom annual log drift and volatility target the initial portfolio weights. Buy-and-hold weights change over time. Bootstrap returns are shifted/scaled when these overrides are active.')
    if backtest:
        synthetic = data.get('demo',False)
        test_start = 'Synthetic' if synthetic else returns.index[-12].date().isoformat()
        test_end = 'Synthetic' if synthetic else returns.index[-1].date().isoformat()
        train_end = 'Synthetic' if synthetic else returns.index[-13].date().isoformat()
        result['backtest_info'] = {'test_start':test_start,'test_end':test_end,'train_end':train_end,
                                   'training_months':len(fit_returns),'synthetic':synthetic}
        result['warnings'].append(('Synthetic demonstration, not real historical performance. ' if synthetic else '') +
            'Backtest: final 12 months held out; earlier months used for fitting. Hypothetical replay of today’s selected holdings and starting allocation, not your actual account history. Current selection can introduce survivorship bias; manually chosen assumptions may use hindsight.')
    return result
