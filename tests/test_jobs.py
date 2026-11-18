import time
from threading import Event
import numpy as np
import pytest
from app import create_app, demo_result
from portfolio_sim.jobs import JobManager
from portfolio_sim.experiments import run_experiment

@pytest.fixture
def client(tmp_path):
    app=create_app({'TESTING':True,'CACHE_PATH':tmp_path/'cache.db'})
    yield app.test_client()
    app.extensions['jobs'].close()

def completed(client,key):
    for _ in range(200):
        r=client.get('/api/jobs/'+key).json
        if r['status'] in {'done','error','cancelled'}: return r
        time.sleep(.01)
    pytest.fail('Background job did not finish')

def test_background_is_identical_to_direct(client):
    body={'demo':True,'years':1,'paths':200,'models':['gbm','merton']}
    submitted=client.post('/api/jobs',json=body)
    assert submitted.status_code==202
    result=completed(client,submitted.json['id'])
    assert result['status']=='done'
    direct=run_experiment(demo_result('EUR','All',1,100,42,prepare_only=True),body)
    assert result['result']['comparisons']==direct['comparisons']
    assert result['progress']==100

def test_job_errors_are_visible(client):
    client.application.extensions['jobs'].prepare=lambda body: {'returns':np.zeros((36,50)), 'values':np.ones(50), 'demo':True}
    r=client.post('/api/jobs',json={'demo':True,'models':['heston'],'years':30,'paths':200000})
    out=completed(client,r.json['id'])
    assert out['status']=='error' and 'too large' in out['error']

def test_invalid_options_rejected_before_fetch(client):
    assert client.post('/api/jobs',json={'models':['other']}).status_code==400
    assert client.post('/api/jobs',json={'demo':True,'parameters':{'rho':2}}).status_code==400
    assert client.post('/api/jobs',json={'demo':True,'backtest':'true'}).status_code==400

def test_unknown_job_and_origin(client):
    assert client.get('/api/jobs/missing').status_code==404
    assert client.post('/api/jobs',json={'demo':True},headers={'Origin':'https://other.example'}).status_code==403

def test_cancel_during_preparation(client):
    manager=client.application.extensions['jobs'];started=Event();release=Event()
    original=manager.prepare
    def waiting(body):
        started.set();release.wait(2);return original(body)
    manager.prepare=waiting
    key=client.post('/api/jobs',json={'demo':True}).json['id']
    assert started.wait(1)
    assert client.post('/api/jobs/'+key+'/cancel').status_code==200
    release.set()
    assert completed(client,key)['status']=='cancelled'

def test_demo_only_jobs_cannot_fetch_market(tmp_path):
    app=create_app({'TESTING':True,'DEMO_ONLY':True,'CACHE_PATH':tmp_path/'cache.db'})
    c=app.test_client()
    assert c.post('/api/jobs',json={'holdings':[{'symbol':'AAPL','quantity':1}]}).status_code==400
    app.extensions['jobs'].close()
