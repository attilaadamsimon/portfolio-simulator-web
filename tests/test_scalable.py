import csv
import io

import pytest

from app import create_app
from portfolio_sim.imports import InputError, inspect_csv, parse_holdings


def export(events):
    out = io.StringIO()
    writer = csv.writer(out, delimiter=';')
    writer.writerow(['date','time','status','reference','description','assetType','type','isin','shares','price','amount','currency'])
    for i, event in enumerate(events):
        row = dict(date=f'2026-09-{i+1:02}', time='12:00:00', status='Executed', reference=f'test-{i}', description='Example security', assetType='Security', type='Buy', isin='US0378331005', shares='1,5', price='10,00', amount='15,00', currency='EUR')
        row.update(event)
        writer.writerow(row.values())
    return out.getvalue().encode()


def test_buy_sell_savings_reinvestment_and_ignored_rows():
    raw = export([{}, {'type':'Savings plan','shares':'0,25'}, {'type':'Reinvestment_Distribution','shares':'0,005'}, {'type':'Sell','shares':'0,5'}, {'type':'Distribution','shares':''}, {'status':'Pending'}, {'status':'Cancelled'}, {'assetType':'Cash','type':'Deposit','isin':'','shares':''}])
    assert inspect_csv(raw)['format'] == 'scalable_transactions'
    r = parse_holdings(raw, decimal='.')
    assert r['holdings'][0]['quantity'] == 1.255
    assert r['skipped'] == 4
    assert r['warnings']


def test_newest_first_order_and_sold_positions():
    raw = export([{'date':'2026-09-03','type':'Sell','shares':'1,5'}, {'date':'2026-09-01'}, {'date':'2026-09-04','isin':'IE00B5BMR087','shares':'0,25'}])
    r = parse_holdings(raw)
    assert len(r['holdings']) == 1
    assert r['holdings'][0]['identifier'] == 'IE00B5BMR087'


def test_duplicates_not_double_counted():
    raw = export([{}, {'date':'2026-09-01','reference':'test-0'}])
    r = parse_holdings(raw)
    assert r['holdings'][0]['quantity'] == 1.5
    assert r['duplicates'] == 1


@pytest.mark.parametrize('events,match', [
    ([{'type':'Sell'}], 'full history'),
    ([{}, {'reference':'test-0'}], 'conflicting'),
    ([{'type':'Stock split'}], 'unsupported share-changing'),
    ([{'status':'Unknown'}], 'unknown transaction status'),
    ([{}, {'shares':'1.25'}], 'mixed decimal'),
])
def test_unsafe_imports_are_rejected(events, match):
    with pytest.raises(InputError, match=match):
        parse_holdings(export(events))


def test_api_accepts_scalable_export(tmp_path):
    c = create_app({'TESTING':True, 'CACHE_PATH':tmp_path/'cache.db'}).test_client()
    raw = export([{}, {'type':'Sell','shares':'0,5'}])
    inspected = c.post('/api/inspect', data={'file':(io.BytesIO(raw),'scalable.csv')})
    assert inspected.status_code == 200
    assert inspected.json['format'] == 'scalable_transactions'
    imported = c.post('/api/import', data={'file':(io.BytesIO(raw),'scalable.csv')})
    assert imported.status_code == 200
    assert imported.json['holdings'][0]['quantity'] == 1
