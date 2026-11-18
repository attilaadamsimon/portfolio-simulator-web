import pytest

from app import create_app
from portfolio_sim.market import MarketData, MarketError


def test_prefers_german_eur_listing_and_remembers(tmp_path, monkeypatch):
    m = MarketData(tmp_path/'cache.db')
    candidates = [{'symbol':'VWRA.L','exchange':'London','kind':'ETF'}, {'symbol':'VWCE.DE','exchange':'XETRA','kind':'ETF'}]
    monkeypatch.setattr(m, 'search', lambda q: candidates)
    monkeypatch.setattr(m, 'asset', lambda s: {'kind':'ETF','currency':'EUR','exchange':'XETRA'})
    assert m.resolve_listing('IE00BK5BQT80')['symbol'] == 'VWCE.DE'
    monkeypatch.setattr(m, 'search', lambda q: pytest.fail('Saved listing should avoid another search'))
    assert m.resolve_listing('IE00BK5BQT80')['symbol'] == 'VWCE.DE'


def test_us_primary_listing_and_fallback_when_unavailable(tmp_path, monkeypatch):
    m = MarketData(tmp_path/'cache.db')
    candidates = [{'symbol':'APC.DE','exchange':'XETRA','kind':'Stock'}, {'symbol':'AAPL','exchange':'NasdaqGS','kind':'Stock'}]
    monkeypatch.setattr(m, 'search', lambda q: candidates)
    def load(symbol):
        if symbol == 'AAPL': raise MarketError('Unavailable')
        return {'kind':'Stock','currency':'EUR','exchange':'XETRA'}
    monkeypatch.setattr(m, 'asset', load)
    assert m.resolve_listing('US0378331005')['symbol'] == 'APC.DE'


def test_no_match_never_invents_ticker(tmp_path, monkeypatch):
    m = MarketData(tmp_path/'cache.db')
    monkeypatch.setattr(m, 'search', lambda q: [])
    assert m.resolve_listing('US0378331005') is None


def test_verified_alphabet_fallback_preserves_share_class(tmp_path, monkeypatch):
    m = MarketData(tmp_path/'cache.db')
    monkeypatch.setattr(m, 'search', lambda q: [])
    calls = []
    def load(symbol):
        calls.append(symbol)
        return {'kind':'Stock','currency':'USD','exchange':'NasdaqGS'}
    monkeypatch.setattr(m, 'asset', load)
    assert m.resolve_listing('US02079K3059')['symbol'] == 'GOOGL'
    assert calls == ['GOOGL']


def test_resolution_api_and_validation(tmp_path, monkeypatch):
    app = create_app({'TESTING':True,'CACHE_PATH':tmp_path/'cache.db'})
    monkeypatch.setattr(app.extensions['market'], 'resolve_listing', lambda i,c: {'symbol':'AAPL','kind':'Stock'})
    client = app.test_client()
    r = client.post('/api/resolve',json={'identifiers':['US0378331005'],'currency':'USD'})
    assert r.status_code == 200
    assert r.json['listings']['US0378331005']['symbol'] == 'AAPL'
    for identifiers in [None, [], ['bad'], [12], ['US0378331005']*51]:
        assert client.post('/api/resolve',json={'identifiers':identifiers}).status_code == 400
