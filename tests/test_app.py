from io import BytesIO

import pytest

from app import create_app


@pytest.fixture
def client(tmp_path):
    return create_app({'TESTING':True,'CACHE_PATH':tmp_path/'cache.db'}).test_client()


def test_page_and_chart_bundle(client):
    r=client.get('/')
    assert r.status_code==200
    assert b'Upload CSV' in r.data
    assert 'frame-ancestors' in r.headers['Content-Security-Policy']
    assert client.get('/assets/plotly.min.js').status_code==200


@pytest.mark.parametrize('selection,expected',[('All',15000),('Stock',6500),('ETF',8500)])
def test_demo_filters_and_currencies(client,selection,expected):
    r=client.post('/api/simulate',json={'demo':True,'selection':selection,'currency':'EUR'})
    assert r.status_code==200 and r.json['initial']==expected and r.json['demo']
    usd=client.post('/api/simulate',json={'demo':True,'selection':selection,'currency':'USD'})
    assert usd.json['initial']==pytest.approx(expected*1.1)


def test_upload_roundtrip(client):
    raw=b'Ticker,Quantity,Asset Type\nAAPL,10,Stock\n'
    r=client.post('/api/inspect',data={'file':(BytesIO(raw),'holdings.csv')})
    assert r.json['mapping']['quantity']=='Quantity'
    r=client.post('/api/import',data={'file':(BytesIO(raw),'holdings.csv')})
    assert r.json['holdings'][0]['quantity']==10


@pytest.mark.parametrize('body',[{}, {'demo':True,'currency':'GBP'},{'demo':True,'years':1.2},{'demo':True,'paths':5000000},{'demo':'true'},{'demo':True,'selection':'Options'},[]])
def test_api_rejects_invalid_settings(client,body):
    assert client.post('/api/simulate',json=body).status_code==400


def test_cross_origin_request_rejected(client):
    assert client.post('/api/simulate',json={'demo':True},headers={'Origin':'https://other.example'}).status_code==403


def test_public_demo_mode_blocks_upload_and_market_data(tmp_path):
    c=create_app({'TESTING':True,'DEMO_ONLY':True,'CACHE_PATH':tmp_path/'cache.db'}).test_client()
    assert b'Upload holdings CSV' not in c.get('/').data
    assert c.post('/api/import',data={'file':(BytesIO(b'Ticker,Quantity\nAAPL,5'),'h.csv')}).status_code==400
    assert c.get('/api/search?q=AAPL').status_code==400
    assert c.post('/api/simulate',json={'holdings':[{'symbol':'AAPL','quantity':5}]}).status_code==400
    assert c.post('/api/simulate',json={'demo':True}).status_code==200
