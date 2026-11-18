from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
import requests

from portfolio_sim.imports import InputError
from portfolio_sim.market import MarketData, MarketError, parse_chart


def chart_fixture(currency='USD', kind='EQUITY'):
    def stamp(date): return int(datetime.fromisoformat(date).timestamp())
    return {'meta':{'symbol':'TEST','currency':currency,'instrumentType':kind,'exchangeTimezoneName':'America/New_York','currentTradingPeriod':{'regular':{'end':stamp('2026-10-30T20:00:00+00:00')}}},'timestamp':[stamp('2026-10-29T13:30:00+00:00'),stamp('2026-10-30T13:30:00+00:00')], 'indicators':{'quote':[{'close':[100,110]}],'adjclose':[{'adjclose':[90,100]}]}}


@pytest.mark.parametrize('time,expected', [('2026-10-30T19:00:00+00:00','2026-10-29'),('2026-10-30T20:10:00+00:00','2026-10-29'),('2026-10-30T20:31:00+00:00','2026-10-30'),('2026-10-31T12:00:00+00:00','2026-10-30')])
def test_only_completed_daily_closes(time, expected):
    assert parse_chart(chart_fixture(), datetime.fromisoformat(time))['date'] == expected


def test_minor_units_and_raw_versus_adjusted():
    data = parse_chart(chart_fixture('GBp'), datetime.fromisoformat('2026-10-31T12:00:00+00:00'))
    assert data['currency'] == 'GBP'
    assert data['rows'][-1]['close'] == pytest.approx(1.1)
    assert data['rows'][-1]['adjusted'] == 1


def test_missing_adjustments_stop_simulation():
    payload=chart_fixture();del payload['indicators']['adjclose']
    with pytest.raises(MarketError): parse_chart(payload)


def asset(symbol='AAA', currency='USD', kind='Stock'):
    end = pd.Timestamp.now(tz='UTC').tz_localize(None).normalize() - pd.Timedelta(days=1)
    dates = pd.bdate_range(end=end, periods=1000)
    return {'symbol':symbol,'name':symbol,'currency':currency,'kind':kind,'exchange':'Test','source':'Fixture','date':dates[-1].date().isoformat(),'stale':False,'cached':False,'fallback':False,'retrieved_at':'test','rows':[{'date':date.date().isoformat(),'close':float(100+i*.1),'adjusted':float(50+i*.05)} for i,date in enumerate(dates)]}


def test_cache_hit_and_outage_label(tmp_path):
    m=MarketData(tmp_path/'cache.db');payload=asset()
    first=m.cached('asset:AAA',lambda:payload)
    assert not first['cached']
    def fail(): raise requests.Timeout()
    second=m.cached('asset:AAA',fail)
    assert second['cached'] and not second['fallback']
    third=m.cached('asset:AAA',fail,True)
    assert third['stale'] and third['fallback']
    with pytest.raises(MarketError):m.cached('asset:NEW',fail)


def test_regressed_provider_preserves_newer_saved_data(tmp_path):
    m=MarketData(tmp_path/'cache.db');data=asset();m.cache.put('asset:AAA',data)
    older={**data,'date':'2000-01-01'}
    result=m.cached('asset:AAA',lambda:older,True)
    assert result['date']==data['date']
    assert result['fallback']


def test_valuation_uses_unadjusted_close_and_filters(tmp_path,monkeypatch):
    m=MarketData(tmp_path/'cache.db')
    monkeypatch.setattr(m,'asset',lambda s,force=False:asset(s,'EUR','Stock' if s=='AAA' else 'ETF'))
    holdings=[{'symbol':'AAA','quantity':2,'declared_kind':'Auto'},{'symbol':'BBB','quantity':3,'declared_kind':'Auto'}]
    all_data=m.prepare(holdings,'EUR','All')
    assert all_data['values'].sum() == pytest.approx((100+999*.1)*5)
    assert all_data['months'] >= 24
    stock=m.prepare(holdings,'EUR','Stock')
    etf=m.prepare(holdings,'EUR','ETF')
    assert stock['values'].sum()+etf['values'].sum()==all_data['values'].sum()


def test_fx_moves_returns_and_does_not_look_ahead(tmp_path,monkeypatch):
    m=MarketData(tmp_path/'cache.db');data=asset()
    # Fixed native price: all return variation must come from FX.
    for row in data['rows']:row['close']=100.;row['adjusted']=100.
    rates=[{'date':r['date'],'rate':.8+i*.0001} for i,r in enumerate(data['rows'])]
    rates.append({'date':(datetime.now(timezone.utc).date()+timedelta(days=2)).isoformat(),'rate':9.})
    monkeypatch.setattr(m,'asset',lambda *a:data)
    monkeypatch.setattr(m,'fx',lambda *a:{'rows':rates,'date':rates[-1]['date'],'source':'Test FX','stale':False})
    out=m.prepare([{'symbol':'AAA','quantity':2,'declared_kind':'Auto'}],'EUR','All')
    assert out['values'][0]==pytest.approx(200*(.8+999*.0001))
    assert out['returns'].iloc[:,0].mean()>0
    assert out['holdings'][0]['fx_date']==data['date']


def test_no_silent_missing_or_wrong_kind(tmp_path,monkeypatch):
    m=MarketData(tmp_path/'cache.db');data=asset(kind='ETF')
    monkeypatch.setattr(m,'asset',lambda *a:data)
    with pytest.raises(InputError,match='CSV says'):
        m.prepare([{'symbol':'AAA','quantity':2,'declared_kind':'Stock'}],'USD','All')


def test_old_data_requires_opt_in(tmp_path,monkeypatch):
    m=MarketData(tmp_path/'cache.db');data=asset();data['stale']=True
    monkeypatch.setattr(m,'asset',lambda *a:data)
    h=[{'symbol':'AAA','quantity':2,'declared_kind':'Auto'}]
    with pytest.raises(MarketError,match='older'):
        m.prepare(h,'USD','All')
    assert m.prepare(h,'USD','All',True)['warnings']


def test_history_too_short_is_rejected(tmp_path,monkeypatch):
    m=MarketData(tmp_path/'cache.db');data=asset();data['rows']=data['rows'][-260:]
    monkeypatch.setattr(m,'asset',lambda *a:data)
    with pytest.raises(InputError,match='24 required'):
        m.prepare([{'symbol':'AAA','quantity':2,'declared_kind':'Auto'}],'USD','All')


@pytest.mark.parametrize('count', [100, 251, 260])
def test_short_history_automatically_excluded_and_value_removed(tmp_path, monkeypatch, count):
    m = MarketData(tmp_path/'cache.db')
    good = asset('OLD', 'EUR')
    new = asset('NEW', 'USD')
    new['name'] = 'New company'
    new['rows'] = new['rows'][-count:]
    monkeypatch.setattr(m, 'asset', lambda symbol, force=False: good if symbol == 'OLD' else new)
    monkeypatch.setattr(m, 'fx', lambda *args: pytest.fail('Excluded asset must not require FX'))
    holdings = [{'symbol':s,'quantity':2,'declared_kind':'Auto'} for s in ['NEW','OLD']]
    result = m.prepare(holdings, 'EUR', 'All')
    assert [h['symbol'] for h in result['holdings']] == ['OLD']
    assert list(result['returns'].columns) == ['OLD']
    assert result['values'].tolist() == [2 * good['rows'][-1]['close']]
    assert result['excluded_holdings'][0]['symbol'] == 'NEW'
    assert 'Automatically excluded New company (NEW)' in result['warnings'][0]
    assert ('252' if count < 252 else '24 required') in result['warnings'][0]
    # Exclusion is per run; it never deletes the uploaded holding.
    assert len(holdings) == 2


def test_all_short_history_reports_exclusion_without_simulating(tmp_path, monkeypatch):
    m = MarketData(tmp_path/'cache.db')
    new = asset('NEW');new['rows'] = new['rows'][-50:]
    monkeypatch.setattr(m, 'asset', lambda *args: new)
    with pytest.raises(InputError, match='No holdings with sufficient price history remain') as error:
        m.prepare([{'symbol':'NEW','quantity':1,'declared_kind':'Auto'}], 'USD', 'All')
    assert 'Automatically excluded' in str(error.value)
    assert '50 daily closes' in str(error.value)


def test_fetch_failure_is_not_misreported_as_short_history(tmp_path, monkeypatch):
    m = MarketData(tmp_path/'cache.db')
    def unavailable(*args): raise MarketError('Provider unavailable')
    monkeypatch.setattr(m, 'asset', unavailable)
    with pytest.raises(MarketError, match='Provider unavailable'):
        m.prepare([{'symbol':'NEW','quantity':1,'declared_kind':'Auto'}], 'USD', 'All')
