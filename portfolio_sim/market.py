"""Free daily data, bounded retries, persistent public-data cache and explicit age."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import time
from urllib.parse import quote
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

from .imports import InputError, is_isin, valid_symbol

UTC = timezone.utc

# Verified fallback for a gap in Yahoo's ISIN search index. Class A must not
# become Class C (GOOG). ISIN/class: https://www.boerse-frankfurt.de/equity/alphabet-inc-class-a
# NASDAQ symbol/ISIN: https://www.borsaitaliana.it/secder-listing/2025-01843-OFFICIAL_LISTING_DOCUMENTATION-MjAyNS0wMTg0M09GRklDSUFMX0xJU1RJTkdfRE9DVU1FTlRBVElPTm51bGwxNzQ1OTMwODkzNTMz.pdf
VERIFIED_LISTINGS = {
    'US02079K3059': {'symbol': 'GOOGL', 'name': 'Alphabet Inc. Class A', 'exchange': 'NasdaqGS', 'kind': 'Stock'}
}


class MarketError(InputError):
    pass


class Cache:
    """Only public market data is persisted. Holdings never enter this database."""
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS market_cache (key TEXT PRIMARY KEY, fetched REAL NOT NULL, payload TEXT NOT NULL)")

    def connect(self):
        return sqlite3.connect(self.path, timeout=15)

    def get(self, key):
        with self.connect() as db:
            row = db.execute("SELECT fetched, payload FROM market_cache WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        try:
            return row[0], json.loads(row[1])
        except (ValueError, TypeError):
            return None

    def put(self, key, payload):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO market_cache VALUES (?, ?, ?)", (key, time.time(), json.dumps(payload, allow_nan=False)))


def get_json(url, params):
    response = requests.get(url, params=params, timeout=(5, 18), headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    response.raise_for_status()
    return response.json()


def parse_chart(result, now=None):
    """Never treat an intraday daily bar as a closing price."""
    now = now or datetime.now(UTC)
    meta = result["meta"]
    local_tz = ZoneInfo(meta.get("exchangeTimezoneName", "UTC"))
    today = now.astimezone(local_tz).date()
    period = meta.get("currentTradingPeriod", {}).get("regular", {})
    end = period.get("end")
    today_closed = bool(end and datetime.fromtimestamp(end, local_tz).date() == today and now.timestamp() >= end + 1800)
    timestamps = result.get("timestamp", [])
    quotes = result.get("indicators", {}).get("quote", [{}])[0]
    adj = result.get("indicators", {}).get("adjclose", [{}])[0].get("adjclose")
    if not adj:
        raise MarketError("Adjusted history is unavailable; simulation was stopped.")
    rows = []
    for stamp, close, adjusted in zip(timestamps, quotes.get("close", []), adj):
        day = datetime.fromtimestamp(stamp, local_tz).date()
        if day > today or (day == today and not today_closed):
            continue
        if close is None or adjusted is None:
            continue
        if not np.isfinite(close) or not np.isfinite(adjusted) or close <= 0 or adjusted <= 0:
            continue
        rows.append({"date": day.isoformat(), "close": float(close), "adjusted": float(adjusted)})
    rows = list({r["date"]: r for r in sorted(rows, key=lambda r: r["date"])}.values())
    if not rows:
        raise MarketError("No completed daily closes are available.")
    kind = {"EQUITY": "Stock", "ETF": "ETF", "CURRENCY": "FX"}.get(meta.get("instrumentType"), "Unsupported")
    native = meta.get("currency", "")
    # Yahoo uses GBp/GBX, ZAc and ILA for minor currency units on some exchanges.
    currency, scale = {"GBp": ("GBP", .01), "GBX": ("GBP", .01), "ZAc": ("ZAR", .01), "ILA": ("ILS", .01)}.get(native, (native.upper(), 1.0))
    if len(currency) != 3 or not currency.isalpha():
        raise MarketError("The listing's currency could not be verified.")
    for row in rows:
        row["close"] *= scale
        row["adjusted"] *= scale
    return {"symbol": meta.get("symbol", ""), "name": meta.get("longName") or meta.get("shortName") or meta.get("symbol", ""), "kind": kind, "currency": currency, "exchange": meta.get("fullExchangeName", meta.get("exchangeName", "")), "rows": rows, "source": "Yahoo Finance", "date": rows[-1]["date"]}


class MarketData:
    ttl = 15 * 60

    def __init__(self, cache_path):
        self.cache = Cache(cache_path)

    def chart(self, symbol):
        errors = []
        now = datetime.now(UTC)
        params = {"period1": int((now - timedelta(days=5 * 366)).timestamp()), "period2": int(now.timestamp()), "interval": "1d", "events": "div,splits", "includeAdjustedClose": "true"}
        for host in ("query1", "query2"):
            try:
                data = get_json(f"https://{host}.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}", params)
                results = data.get("chart", {}).get("result")
                if not results:
                    raise MarketError("No data returned")
                parsed = parse_chart(results[0], now)
                if parsed["symbol"].upper() != symbol.upper():
                    raise MarketError("The provider returned a different ticker")
                return parsed
            except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as error:
                errors.append(type(error).__name__)
                time.sleep(.2)
        raise MarketError(f"{symbol}: closing prices are unavailable from Yahoo Finance. Retry later or use a previously saved cache. ({', '.join(errors)})")

    def cached(self, key, fetch, force=False):
        stored = self.cache.get(key)
        now = datetime.now(UTC)
        if stored and not force and time.time() - stored[0] < self.ttl:
            data = dict(stored[1])
            data["retrieved_at"] = datetime.fromtimestamp(stored[0], UTC).isoformat()
            data["cached"] = True
            data["fallback"] = False
        else:
            try:
                data = fetch()
                if stored and data["date"] < stored[1]["date"]:
                    raise MarketError("Provider returned older data than the saved cache")
                self.cache.put(key, data)
                data = {**data, "retrieved_at": now.isoformat(), "cached": False, "fallback": False}
            except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
                if not stored:
                    raise MarketError(f"No data is available for {key.split(':', 1)[-1]}. Check the ticker and connection, then retry.") from None
                data = {**stored[1], "retrieved_at": datetime.fromtimestamp(stored[0], UTC).isoformat(), "cached": True, "fallback": True}
        age = (now.date() - datetime.fromisoformat(data["date"]).date()).days
        data["stale"] = age > 4 or data["fallback"]
        return data

    def asset(self, symbol, force=False):
        return self.cached(f"asset:{symbol}", lambda: self.chart(symbol), force)

    def search(self, query):
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 80:
            raise InputError("Enter a ticker, ISIN or security name.")
        query = query.strip()
        cache_key = "search:" + query.upper()
        stored = self.cache.get(cache_key)
        if stored and time.time() - stored[0] < 86400:
            return stored[1]
        for host in ("query1", "query2"):
            try:
                data = get_json(f"https://{host}.finance.yahoo.com/v1/finance/search", {"q": query, "quotesCount": 10, "newsCount": 0, "enableFuzzyQuery": "false"})
                results = [{"symbol": item["symbol"], "name": item.get("longname") or item.get("shortname") or item["symbol"], "exchange": item.get("exchDisp", item.get("exchange", "")), "kind": "ETF" if item["quoteType"] == "ETF" else "Stock"} for item in data.get("quotes", []) if item.get("quoteType") in {"EQUITY", "ETF"} and item.get("symbol")]
                if results:
                    self.cache.put(cache_key, results)
                    return results
            except (requests.RequestException, ValueError, KeyError, TypeError):
                continue
        return []

    def fx(self, source, target, force=False):
        def fetch():
            start = (datetime.now(UTC) - timedelta(days=5 * 366 + 10)).date().isoformat()
            try:
                data = get_json("https://api.frankfurter.dev/v2/rates", {"base": source, "quotes": target, "from": start})
                rows = [{"date": r["date"], "rate": float(r["rate"])} for r in data if r.get("quote", "").upper() == target and r.get("base", "").upper() == source and np.isfinite(r["rate"]) and r["rate"] > 0]
                rows.sort(key=lambda r: r["date"])
                if len(rows) < 250:
                    raise MarketError("Insufficient FX history")
                return {"rows": rows, "date": rows[-1]["date"], "source": "Frankfurter daily reference rates"}
            except (requests.RequestException, ValueError, KeyError, TypeError):
                chart = self.chart(f"{source}{target}=X")
                return {"rows": [{"date": r["date"], "rate": r["close"]} for r in chart["rows"]], "date": chart["date"], "source": "Yahoo Finance daily FX"}
        return self.cached(f"fx:{source}{target}", fetch, force)

    def resolve_listing(self, identifier, currency='EUR'):
        """Rank exact-ISIN search results; never guess a ticker from its name."""
        if not is_isin(identifier):
            raise InputError('Automatic listing selection needs an ISIN.')
        cache_key = f'listing:{currency}:{identifier}'
        stored = self.cache.get(cache_key)
        if stored and time.time() - stored[0] < 30 * 86400:
            return stored[1]
        candidates = self.search(identifier)
        if not candidates and identifier in VERIFIED_LISTINGS:
            candidates = [VERIFIED_LISTINGS[identifier].copy()]
        def rank(item):
            symbol = item['symbol']
            primary_us = identifier.startswith('US') and item.get('exchange') in {'NASDAQ', 'NasdaqGS', 'NasdaqGM', 'NasdaqCM', 'NYSE', 'New York', 'Nasdaq', 'NYSEArca'}
            preferred = symbol.endswith(('.DE', '.F')) if currency == 'EUR' else ('.' not in symbol)
            return (not primary_us, not preferred, symbol.endswith(('.F', '.SG', '.BE', '.MU')), candidates.index(item))
        for candidate in sorted(candidates, key=rank):
            if not valid_symbol(candidate['symbol']):
                continue
            try:
                data = self.asset(candidate['symbol'])
                if data['kind'] not in {'Stock', 'ETF'}:
                    continue
                chosen = {**candidate, 'kind': data['kind'], 'currency': data['currency'], 'exchange': data['exchange']}
                self.cache.put(cache_key, chosen)
                return chosen
            except MarketError:
                continue
        return None

    def prepare(self, holdings, currency, selection, allow_stale=False, force=False):
        with ThreadPoolExecutor(max_workers=4) as pool:
            assets = list(pool.map(lambda h: self.asset(h["symbol"], force), holdings))
        selected, excluded, removed = [], [], []
        this_month = pd.Timestamp(datetime.now(UTC).date()).to_period('M').start_time
        for_history = lambda d: pd.Series({r['date']: r['adjusted'] for r in d['rows']}, dtype=float)
        for h, data in zip(holdings, assets):
            if data["kind"] not in {"Stock", "ETF"}:
                excluded.append(f"{h['symbol']} (not a stock or ETF)")
                continue
            if h["declared_kind"] != "Auto" and h["declared_kind"] != data["kind"]:
                raise InputError(f"{h['symbol']}: the CSV says {h['declared_kind']}, but market data identifies {data['kind']}. Correct its type before continuing.")
            if selection != "All" and data["kind"] != selection:
                continue
            history = for_history(data).dropna()
            history.index = pd.to_datetime(history.index)
            history = history.sort_index()
            reason = None
            if len(history) < 252:
                reason = f'insufficient price history ({len(history)} daily closes; at least 252, approximately one trading year, required)'
            else:
                ends = history.resample('ME').last()
                dates = pd.Series(history.index, index=history.index).resample('ME').last()
                ends = ends.where((ends.index - pd.DatetimeIndex(dates)) <= pd.Timedelta(days=7))
                ends = ends[ends.index < this_month]
                months = int(np.log(ends / ends.shift(1)).replace([np.inf, -np.inf], np.nan).count())
                if months < 24:
                    reason = f'insufficient price history for this model ({months} complete monthly returns; at least 24 required)'
            if reason:
                removed.append({'symbol': h['symbol'], 'name': data['name'], 'reason': reason})
                continue
            selected.append((h, data))
        if excluded:
            # Explicit feedback; never quietly count an unsupported instrument as equity.
            raise InputError("Remove these unsupported positions and run again: " + ", ".join(excluded))
        removal_messages = [f"Automatically excluded {d['name']} ({d['symbol']}) from the simulation because of {d['reason']}. Its value is excluded from the simulated starting portfolio." for d in removed]
        if not selected:
            raise InputError(' '.join(removal_messages) + ' No holdings with sufficient price history remain in this selection.' if removed else 'There are no holdings in this selection.')
        fx = {native: self.fx(native, currency, force) for native in sorted({d["currency"] for _, d in selected}) if native != currency}
        warnings = []
        for d in [d for _, d in selected] + list(fx.values()):
            if d["stale"]:
                warnings.append(f"{d.get('symbol', 'FX')}: using saved or older data dated {d['date']} (source: {d['source']}).")
        if warnings and not allow_stale:
            raise MarketError("Some prices could not be refreshed or are over four days old. Refresh prices, or enable ‘Allow clearly labeled saved/older data’. " + " ".join(warnings))
        warnings = removal_messages + warnings
        series, values, details = {}, [], []
        for h, d in selected:
            history = pd.DataFrame(d["rows"]).set_index("date")
            history.index = pd.to_datetime(history.index)
            close = float(history["close"].iloc[-1])
            adjusted = history["adjusted"].astype(float)
            rate, fx_date, fx_source = 1., None, None
            if d["currency"] != currency:
                f = fx[d["currency"]]
                rates = pd.Series({r["date"]: r["rate"] for r in f["rows"]}, dtype=float)
                rates.index = pd.to_datetime(rates.index)
                rates = rates.sort_index()
                aligned = rates.reindex(adjusted.index, method="ffill", tolerance=pd.Timedelta(days=7))
                adjusted = adjusted * aligned
                eligible = rates[rates.index <= history.index[-1]]
                if eligible.empty or pd.isna(aligned.iloc[-1]):
                    raise MarketError(f"No sufficiently recent exchange rate for {h['symbol']}.")
                rate = float(eligible.iloc[-1])
                fx_date = eligible.index[-1].date().isoformat()
                fx_source = f["source"]
            value = h["quantity"] * close * rate
            values.append(value)
            series[h["symbol"]] = adjusted
            details.append({"symbol": h["symbol"], "name": d["name"], "kind": d["kind"], "quantity": h["quantity"], "currency": d["currency"], "close": close, "date": d["date"], "value": value, "exchange": d["exchange"], "source": d["source"], "retrieved_at": d["retrieved_at"], "cached": d["cached"], "stale": d["stale"], "fx_rate": rate, "fx_date": fx_date, "fx_source": fx_source})
        if not np.isfinite(values).all() or not 0 < sum(values) <= 1e13:
            raise InputError("Portfolio value must be positive and below 10 trillion.")
        # Use common complete calendar months: no artificial zero holiday returns,
        # no mixing unequal daily return intervals across exchanges.
        monthly = {}
        this_month = pd.Timestamp(datetime.now(UTC).date()).to_period("M").start_time
        for symbol, s in series.items():
            s = s.dropna()
            if len(s) < 252:
                raise InputError(f"{symbol}: at least one year of daily history is required.")
            ends = s.resample("ME").last()
            dates = pd.Series(s.index, index=s.index).resample("ME").last()
            # Drop months whose last quote is implausibly early (suspensions/gaps).
            valid = (ends.index - pd.DatetimeIndex(dates)) <= pd.Timedelta(days=7)
            ends = ends.where(valid)
            ends = ends[ends.index < this_month]
            monthly[symbol] = ends
        prices = pd.DataFrame(monthly)
        returns = np.log(prices / prices.shift(1)).replace([np.inf, -np.inf], np.nan).dropna()
        if len(returns) < 24:
            raise InputError("At least 24 shared, complete monthly returns are needed. One or more holdings have too little history.")
        if (returns.abs() > np.log(5)).any().any():
            raise MarketError("An extreme historical price discontinuity was detected. Check for a split or bad data before simulating.")
        dates = [d["date"] for _, d in selected]
        if min(dates) != max(dates):
            warnings.append("Markets have different latest closing dates; values use each listing's latest completed close.")
        return {"returns": returns, "values": np.array(values), "holdings": details, "excluded_holdings": removed, "warnings": warnings, "history_start": returns.index[0].date().isoformat(), "history_end": returns.index[-1].date().isoformat(), "months": len(returns)}
