"""Run `python app.py` and open http://127.0.0.1:8050."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from threading import BoundedSemaphore
from urllib.parse import urlparse

from flask import Flask, jsonify, render_template, request, send_file
import numpy as np
import plotly
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

from portfolio_sim.imports import InputError, inspect_csv, parse_holdings, validate_holdings, is_isin
from portfolio_sim.market import MarketData
from portfolio_sim.simulation import simulate
from portfolio_sim.jobs import register_jobs

ROOT = Path(__file__).resolve().parent


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(MAX_CONTENT_LENGTH=2 * 1024 * 1024 + 65536, DEMO_ONLY=os.getenv("DEMO_ONLY", "0") == "1")
    if test_config:
        app.config.update(test_config)
    market = MarketData(app.config.get("CACHE_PATH", os.getenv("MARKET_CACHE", str(ROOT / ".cache" / "market.sqlite3"))))
    app.extensions["market"] = market
    slots = BoundedSemaphore(2)

    @app.before_request
    def same_origin():
        if request.method == "POST" and request.headers.get("Origin"):
            if urlparse(request.headers["Origin"]).netloc != request.host:
                return jsonify(error="Open the simulator directly to submit a portfolio."), 403

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(InputError)
    def input_error(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_):
        return jsonify(error="Choose a CSV smaller than 2 MB."), 413

    @app.errorhandler(BadRequest)
    def bad_request(_):
        return jsonify(error="Invalid request. Check the uploaded file or simulation settings."), 400

    @app.get("/")
    def index():
        return render_template("index.html", demo_only=app.config["DEMO_ONLY"])

    @app.get("/how-it-works")
    def how_it_works():
        return render_template("how-it-works.html")

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.get("/assets/plotly.min.js")
    def plotly_js():
        return send_file(Path(plotly.__file__).parent / "package_data" / "plotly.min.js", mimetype="application/javascript", max_age=86400)

    @app.get("/api/template")
    def template():
        return send_file(ROOT / "examples" / "holdings.csv", as_attachment=True)

    def upload():
        if app.config["DEMO_ONLY"]:
            raise InputError("This showcase runs on synthetic data. Run the Python project locally to upload holdings.")
        file = request.files.get("file")
        if file is None or not file.filename:
            raise InputError("Choose a holdings CSV first.")
        return file.read()

    @app.post("/api/inspect")
    def inspect():
        return jsonify(inspect_csv(upload()))

    @app.post("/api/import")
    def import_csv():
        try:
            mapping = json.loads(request.form["mapping"]) if "mapping" in request.form else None
        except ValueError:
            raise InputError("Invalid column mapping.") from None
        return jsonify(parse_holdings(upload(), mapping, request.form.get("decimal", ".")))

    @app.get("/api/search")
    def search():
        if app.config["DEMO_ONLY"]:
            raise InputError("Listing search is available in local mode.")
        return jsonify(results=market.search(request.args.get("q", "")))

    @app.post('/api/resolve')
    def resolve():
        if app.config['DEMO_ONLY']:
            raise InputError('Listing search is available in local mode.')
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise InputError('Provide ISINs to resolve.')
        identifiers = body.get('identifiers')
        currency = body.get('currency', 'EUR')
        if currency not in {'EUR', 'USD'} or not isinstance(identifiers, list) or not 1 <= len(identifiers) <= 50 or any(not isinstance(i, str) or not is_isin(i) for i in identifiers):
            raise InputError('Provide up to 50 valid ISINs and EUR or USD.')
        identifiers = list(dict.fromkeys(identifiers))
        with ThreadPoolExecutor(max_workers=4) as pool:
            choices = list(pool.map(lambda i: market.resolve_listing(i, currency), identifiers))
        return jsonify(listings=dict(zip(identifiers, choices)))

    @app.post("/api/simulate")
    def run():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise InputError("Send valid simulation settings.")
        currency, selection = body.get("currency", "EUR"), body.get("selection", "All")
        if currency not in {"EUR", "USD"} or selection not in {"All", "Stock", "ETF"}:
            raise InputError("Select EUR/USD and All/Stock/ETF.")
        for option in ("demo", "allow_stale", "refresh"):
            if option in body and not isinstance(body[option], bool):
                raise InputError(f"Invalid {option} setting.")
        years, paths, seed = body.get("years", 10), body.get("paths", 2000), body.get("seed", 42)
        # Validate cheap settings before any external market calls.
        for label, value, low, high in [("Years", years, 1, 30), ("Paths", paths, 100, 5000), ("Seed", seed, 0, 2**32 - 1)]:
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise InputError(f"{label} must be an integer between {low} and {high}.")
        if not slots.acquire(blocking=False):
            return jsonify(error="Two simulations are already running. Please retry shortly."), 429
        try:
            if body.get("demo", False):
                result = demo_result(currency, selection, years, paths, seed)
            else:
                if app.config["DEMO_ONLY"]:
                    raise InputError("This showcase uses synthetic data only.")
                holdings = validate_holdings(body.get("holdings"))
                prepared = market.prepare(holdings, currency, selection, body.get("allow_stale", False), body.get("refresh", False))
                result = simulate(prepared.pop("returns"), prepared.pop("values"), years, paths, seed)
                result.update(prepared, demo=False)
            result.update(currency=currency, selection=selection, calculated_at=datetime.now(timezone.utc).isoformat())
            return jsonify(result)
        finally:
            slots.release()

    def validate_job_portfolio(body):
        if not body.get("demo", False):
            if app.config["DEMO_ONLY"]:
                raise InputError("This showcase uses synthetic data only.")
            validate_holdings(body.get("holdings"))

    def prepare_job(body):
        currency, selection = body.get("currency", "EUR"), body.get("selection", "All")
        if body.get("demo", False):
            return demo_result(currency, selection, 1, 100, 42, prepare_only=True)
        holdings = validate_holdings(body.get("holdings"))
        prepared = market.prepare(holdings, currency, selection, body.get("allow_stale", False), body.get("refresh", False))
        return dict(prepared, demo=False)

    # Keep the original synchronous endpoint for compatibility and parity checks.
    register_jobs(app, prepare_job, validate_job_portfolio)
    return app


def demo_result(currency, selection, years, paths, seed, prepare_only=False):
    """A shareable, offline showcase; these are not real securities or prices."""
    rng = np.random.default_rng(2026)
    common = rng.normal(0, .025, (60, 1))
    returns = common + rng.normal([.005, .006, .004], [.035, .045, .018], (60, 3))
    returns = returns - returns.mean(axis=0) + [.005, .006, .004]
    types = np.array(["Stock", "Stock", "ETF"])
    mask = types != "" if selection == "All" else types == selection
    factor = 1 if currency == "EUR" else 1.1
    values = np.array([4000., 2500., 8500.]) * factor
    result = {"returns": returns[:, mask], "values": values[mask]} if prepare_only else simulate(returns[:, mask], values[mask], years, paths, seed)
    result.update(demo=True, holdings=[{"symbol": ["DEMO-A", "DEMO-B", "DEMO-ETF"][i], "name": ["Example stock A", "Example stock B", "Example ETF"][i], "kind": types[i], "quantity": [20, 25, 50][i], "currency": currency, "close": float(values[i] / [20, 25, 50][i]), "value": float(values[i]), "date": "Synthetic", "exchange": "Example", "source": "Synthetic data", "stale": False, "cached": False, "fx_date": None, "fx_rate": 1, "fx_source": None, "retrieved_at": None} for i in range(3) if mask[i]], warnings=[], history_start="Synthetic", history_end="Synthetic", months=60)
    return result


app = create_app()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8050")))
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=False, threaded=True)
