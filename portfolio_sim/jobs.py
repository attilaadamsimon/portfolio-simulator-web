"""Bounded in-memory background jobs using Python's standard library only."""
from concurrent.futures import ThreadPoolExecutor
from secrets import token_urlsafe
from threading import Event, Lock
from time import monotonic

from flask import jsonify, request
from .imports import InputError
from .experiments import validate_request, run_experiment
from .models import Cancelled, MODEL_NAMES, DEFAULTS
from .scenarios import PRESETS, SCENARIOS


class JobManager:
    def __init__(self, prepare, logger, workers=2):
        self.prepare, self.logger = prepare, logger
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='portfolio')
        self.lock = Lock()
        self.jobs = {}

    def _clean(self, make_room=False):
        now = monotonic()
        for key, job in list(self.jobs.items()):
            if now-job['created'] > 900:
                job['cancel'].set()
                del self.jobs[key]
        # Keep a bounded number of results, evicting oldest completed jobs first.
        if make_room and len(self.jobs) >= 16:
            for key, job in list(self.jobs.items()):
                if job['status'] in {'done','error','cancelled'}:
                    del self.jobs[key]
                    break

    def submit(self, body):
        validate_request(body)
        with self.lock:
            self._clean(make_room=True)
            if sum(j['status'] in {'queued','running','cancelling'} for j in self.jobs.values()) >= 8 or len(self.jobs) >= 16:
                raise InputError('The simulation queue is full. Cancel an earlier run or retry shortly.')
            key = token_urlsafe(32)
            job = {'status':'queued','progress':0,'message':'Waiting for a simulation slot…',
                   'created':monotonic(),'cancel':Event(),'result':None,'error':None}
            self.jobs[key] = job
            job['future'] = self.pool.submit(self._run, job, body)
        return key

    def _run(self, job, body):
        def check():
            if monotonic()-job['created'] > 600:
                raise InputError('This run exceeded 10 minutes. Reduce paths, holdings or years and try again.')
            return job['cancel'].is_set()
        def update(p, message):
            with self.lock:
                if not job['cancel'].is_set():
                    job.update(progress=round(5+94*p,1),message=message)
        try:
            if check():
                raise Cancelled()
            with self.lock:
                job.update(status='running',message='Preparing completed prices and history…')
            prepared = self.prepare(body)
            if check():
                raise Cancelled()
            result = run_experiment(prepared, body, update, check)
            with self.lock:
                if job['cancel'].is_set():
                    job.update(status='cancelled',message='Cancelled.')
                else:
                    job.update(status='done',progress=100,message='Complete',result=result)
        except Cancelled:
            with self.lock:
                job.update(status='cancelled',message='Cancelled.')
        except Exception as exc:
            if not isinstance(exc,InputError):
                self.logger.exception('Background simulation failed')
            with self.lock:
                job.update(status='error',error=str(exc) if isinstance(exc,InputError) else 'The simulation failed. Please retry with fewer paths.')

    def get(self, key):
        with self.lock:
            self._clean()
            job = self.jobs.get(key)
            if not job:
                return None
            return {k:job[k] for k in ('status','progress','message','result','error')}

    def cancel(self, key):
        with self.lock:
            job = self.jobs.get(key)
            if not job:
                return False
            if job['status'] in {'queued','running','cancelling'}:
                job['cancel'].set()
                queued = job['future'].cancel()
                job.update(status='cancelled' if queued else 'cancelling',
                           message='Cancelling; any price request already in progress must finish first…')
            return True

    def close(self):
        with self.lock:
            for job in self.jobs.values():
                job['cancel'].set()
        self.pool.shutdown(wait=True,cancel_futures=True)


def register_jobs(app, prepare, validate_portfolio):
    manager = JobManager(prepare,app.logger)
    app.extensions['jobs'] = manager

    @app.get('/api/model-options')
    def model_options():
        return jsonify(models=MODEL_NAMES,defaults=DEFAULTS,presets=PRESETS,scenarios=SCENARIOS)

    @app.post('/api/jobs')
    def submit_job():
        body = request.get_json(silent=True)
        validate_request(body)
        validate_portfolio(body)
        return jsonify(id=manager.submit(body)),202

    @app.get('/api/jobs/<key>')
    def get_job(key):
        job = manager.get(key)
        return (jsonify(job),200) if job else (jsonify(error='Run expired or the server restarted. Run the simulation again.'),404)

    @app.post('/api/jobs/<key>/cancel')
    def cancel_job(key):
        return (jsonify(cancelled=True),200) if manager.cancel(key) else (jsonify(error='Run not found.'),404)
