from datetime import datetime
from decimal import Decimal
import csv
import io
import math
import re
import unicodedata


class InputError(ValueError):
    pass


def key(value):
    plain = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", plain.lower())


ALIASES = {
    "identifier": ["ticker", "symbol", "ticker symbol", "isin", "instrument", "security identifier"],
    "quantity": ["quantity", "shares", "qty", "units", "anzahl", "stuck", "stueck", "bestand", "anzahl anteile", "no. of shares"],
    "name": ["name", "description", "security name", "bezeichnung", "wertpapier", "produkt", "instrument name"],
    "kind": ["asset type", "asset_type", "type", "security type", "asset class", "wertpapiertyp", "gattung", "produktart"],
}
STOCK = {"stock", "stocks", "equity", "equities", "aktie", "aktien", "commonstock"}
ETF = {"etf", "etfs", "exchangetradedfund"}
EXCLUDED = {"option", "options", "warrant", "warrants", "optionsschein", "derivative", "derivatives", "derivat", "derivate", "future", "futures", "cfd", "cash", "bond", "bonds", "anleihe", "crypto", "cryptocurrency", "krypto", "etn", "etc", "certificate", "zertifikat", "mutualfund", "fee", "fees", "tax", "taxes"}
TRANSACTION_HEADERS = {"transcode", "transactiontype", "transaktionstyp", "buchungsart", "activitydate", "settledate", "transactiondate", "orderid"}
TRANSACTION_ACTIONS = {"buy", "sell", "kauf", "verkauf", "sparplan", "dividend", "dividende", "deposit", "withdrawal", "einzahlung", "auszahlung"}


def scalable_columns(headers):
    columns = {key(h): h for h in headers}
    required = {'date', 'status', 'reference', 'description', 'assettype', 'type', 'isin', 'shares', 'price', 'amount', 'currency'}
    return columns if required <= columns.keys() else None


def read_csv(raw):
    if not raw or len(raw) > 2 * 1024 * 1024:
        raise InputError("Choose a non-empty holdings CSV smaller than 2 MB.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("cp1252")
        except UnicodeDecodeError:
            raise InputError("Save your CSV as UTF-8 and try again.") from None
    text = text.strip()
    if not text or "\x00" in text:
        raise InputError("Use a text CSV file with a header row.")
    lines = text.splitlines()
    if lines[0].lower().startswith("sep=") and len(lines[0]) == 5:
        delimiter = lines.pop(0)[-1]
        text = "\n".join(lines)
    else:
        try:
            delimiter = csv.Sniffer().sniff(text[:16000], delimiters=",;\t").delimiter
        except csv.Error:
            delimiter = ";" if ";" in lines[0] else ","
    try:
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter, strict=True)
        headers = reader.fieldnames or []
        if not headers or len(headers) > 60 or any(not key(h) for h in headers) or len(set(map(key, headers))) != len(headers):
            raise InputError("Use one header row with unique, non-empty column names.")
        scalable = scalable_columns(headers)
        if not scalable and set(map(key, headers)) & TRANSACTION_HEADERS:
            raise InputError("This looks like a transaction report. Upload current holdings (one row per position), not purchases and sales.")
        rows = []
        for row in reader:
            if None in row or None in row.values():
                raise InputError(f"Row {reader.line_num}: the number of columns does not match the header.")
            if any(v.strip() for v in row.values()):
                rows.append(row)
            if len(rows) > (20000 if scalable else 500):
                raise InputError("Use at most 20,000 Scalable transactions or 500 holdings rows.")
    except csv.Error:
        raise InputError("Invalid CSV formatting. Check the separator and quotation marks.") from None
    if not rows:
        raise InputError("The CSV has no holdings.")

    action_columns = [h for h in headers if key(h) in {"type", "typ", "action", "aktion"}]
    if not scalable and any(key(row[h]) in TRANSACTION_ACTIONS for row in rows for h in action_columns):
        raise InputError("This contains transactions. Upload a current holdings snapshot instead.")
    return headers, rows


def inspect_csv(raw):
    headers, rows = read_csv(raw)
    lookup = {key(h): h for h in headers}
    mapping = {field: next((lookup[key(a)] for a in aliases if key(a) in lookup), "") for field, aliases in ALIASES.items()}
    scalable = scalable_columns(headers)
    if scalable:
        mapping = {'identifier': scalable['isin'], 'quantity': scalable['shares'], 'name': scalable['description'], 'kind': ''}
    return {"headers": headers, "mapping": mapping, "preview": rows[:4], "rows": len(rows), "format": "scalable_transactions" if scalable else "holdings"}


def parse_scalable(headers, rows):
    columns = scalable_columns(headers)
    get = lambda row, field: str(row.get(columns.get(field), '') or '').strip()


    decimal_marks = {mark for row in rows for mark in (',', '.') if mark in get(row, 'shares')}
    if len(decimal_marks) > 1:
        raise InputError('Scalable shares have mixed decimal separators. Re-export with one number format.')
    decimal = next(iter(decimal_marks), '.')
    dated = []
    for index, row in enumerate(rows, 2):
        try:
            date = datetime.fromisoformat(get(row, 'date') + 'T' + (get(row, 'time') or '00:00:00'))
        except ValueError:
            raise InputError(f'Row {index}: invalid Scalable transaction date/time.') from None
        dated.append((date, index, row))
    balances, names, seen = {}, {}, {}
    skipped, duplicates = 0, 0
    additions = {'buy', 'savingsplan', 'reinvestmentdistribution'}
    cash_actions = {'distribution', 'dividend', 'deposit', 'withdrawal', 'interest', 'fee', 'tax'}
    for date, index, row in sorted(dated, key=lambda entry: entry[0]):
        status = key(get(row, 'status'))
        if status in {'cancelled', 'canceled', 'pending', 'rejected', 'failed'}:
            skipped += 1
            continue
        if status != 'executed':
            raise InputError(f'Row {index}: unknown transaction status. Only Executed transactions are supported.')
        reference = get(row, 'reference')
        if reference:
            fingerprint = tuple(get(row, f) for f in ['date', 'time', 'isin', 'shares', 'type', 'assettype', 'amount', 'currency'])
            if reference in seen:
                if seen[reference] != fingerprint:
                    raise InputError(f'Row {index}: conflicting rows share the same transaction reference.')
                duplicates += 1
                continue
            seen[reference] = fingerprint
        action, asset = key(get(row, 'type')), key(get(row, 'assettype'))
        name = get(row, 'description')
        if asset in EXCLUDED or action in cash_actions or re.search(r'\b(option|optionsschein|warrant|knock.?out|turbo|cfd|future)\b', name, re.I):
            skipped += 1
            continue
        if asset not in {'security'} | STOCK | ETF:
            raise InputError(f'Row {index}: unsupported Scalable asset type. Review this transaction.')
        if action not in additions | {'sell'}:
            raise InputError(f'Row {index}: unsupported share-changing transaction “{get(row, "type")}”. Transfers or corporate actions need review.')
        ident = get(row, 'isin').upper()
        if not is_isin(ident):
            raise InputError(f'Row {index}: missing or invalid ISIN for a securities transaction.')
        text = get(row, 'shares')
        if not re.fullmatch(r'\d+(?:' + re.escape(decimal) + r'\d+)?', text):
            raise InputError(f'Row {index}: invalid share quantity.')
        count = Decimal(text.replace(',', '.'))
        if count <= 0 or count > Decimal('1e12'):
            raise InputError(f'Row {index}: share quantity must be positive.')
        balances[ident] = balances.get(ident, Decimal(0)) + (-count if action == 'sell' else count)
        names[ident] = name[:160]
        if balances[ident] < Decimal('-0.000000001'):
            raise InputError(f'{ident}: a sale exceeds the earlier purchases in this file. Export the full history, including purchases before the first sale, or upload current holdings.')
        if abs(balances[ident]) <= Decimal('0.000000001'):
            balances[ident] = Decimal(0)
    holdings = [{'identifier': ident, 'symbol': '', 'name': names[ident], 'quantity': float(count), 'declared_kind': 'Auto'} for ident, count in balances.items() if count > 0]
    if not holdings:
        raise InputError('No remaining positive holdings were found in these transactions.')
    if len(holdings) > 50:
        raise InputError('Use at most 50 distinct remaining holdings.')
    as_of = max(d[0] for d in dated).date().isoformat()
    return {'holdings': holdings, 'skipped': skipped, 'duplicates': duplicates, 'format': 'scalable_transactions', 'as_of': as_of,
            'warnings': [f'Holdings reconstructed from this export through {as_of}. This must include your full transaction history; later trades, missing transfers and corporate actions are not included. Review the quantities against your broker.']}


def quantity(value, decimal):
    text = str(value).strip().replace("\u00a0", "").replace(" ", "").replace("'", "")
    if decimal not in {".", ","}:
        raise InputError("Choose a decimal separator.")
    grouping = "," if decimal == "." else "."
    pattern = rf"[+\-]?(?:\d+|\d{{1,3}}(?:{re.escape(grouping)}\d{{3}})+)(?:{re.escape(decimal)}\d+)?"
    if not re.fullmatch(pattern, text):
        raise InputError(f"Invalid quantity ‘{value}’. Check the decimal separator.")
    result = float(text.replace(grouping, "").replace(decimal, "."))
    if not math.isfinite(result) or result < 0 or result > 1e12:
        raise InputError("Quantities must be finite, non-negative numbers (no short positions).")
    return result


def is_isin(value):
    return bool(re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}\d", value))


def valid_symbol(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Z0-9][A-Z0-9.\-^=]{0,24}", value)) and not is_isin(value)


def parse_holdings(raw, mapping=None, decimal="."):
    info = inspect_csv(raw)
    headers, rows = read_csv(raw)
    if scalable_columns(headers):
        return parse_scalable(headers, rows)
    mapping = info["mapping"] if mapping is None else mapping
    if not isinstance(mapping, dict) or any(f not in ALIASES or (h and h not in headers) for f, h in mapping.items()):
        raise InputError("The column mapping does not match this file.")
    if not mapping.get("identifier") or not mapping.get("quantity"):
        raise InputError("Select an identifier column and a quantity column.")
    used = [v for v in mapping.values() if v]
    if len(used) != len(set(used)):
        raise InputError("Map each column to only one field.")
    holdings, skipped = {}, 0
    for row in rows:
        get = lambda f: str(row.get(mapping.get(f), "") or "").strip()
        ident, name, kind = get("identifier").upper(), get("name"), key(get("kind"))
        if kind in EXCLUDED or re.search(r"\d{6}[CP]\d{8}$", ident) or re.search(r"\b(option|optionsschein|warrant|knock.?out|turbo|cfd|future)\b", name, re.I):
            skipped += 1
            continue
        if not (is_isin(ident) or valid_symbol(ident)):
            raise InputError(f"‘{ident or '(blank)'}’ is not a ticker or ISIN. Map the correct identifier column.")
        q = quantity(get("quantity"), decimal)
        if q == 0:
            skipped += 1
            continue
        declared = "Stock" if kind in STOCK else "ETF" if kind in ETF else "Auto"
        if kind and declared == "Auto":
            raise InputError(f"Unknown asset type ‘{get('kind')}’ for {ident}. Map Stock/ETF types or leave the type column unmapped for market-data classification.")
        if ident in holdings:
            if holdings[ident]["declared_kind"] != declared:
                raise InputError(f"Conflicting asset types for {ident}.")
            holdings[ident]["quantity"] += q
        else:
            holdings[ident] = {"identifier": ident, "symbol": "" if is_isin(ident) else ident, "name": name[:160], "quantity": q, "declared_kind": declared}
    if not holdings:
        raise InputError("No positive stock or ETF holdings were found.")
    if len(holdings) > 50:
        raise InputError("Use at most 50 distinct holdings.")
    return {"holdings": list(holdings.values()), "skipped": skipped}


def validate_holdings(rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 50:
        raise InputError("Provide between 1 and 50 holdings.")
    merged = {}
    for row in rows:
        if not isinstance(row, dict):
            raise InputError("Invalid holding.")
        symbol = str(row.get("symbol", "")).strip().upper()
        if not valid_symbol(symbol):
            raise InputError("Every holding needs a confirmed exchange ticker (for example AAPL or VWCE.DE).")
        q = row.get("quantity")
        if isinstance(q, bool) or not isinstance(q, (int, float)) or not math.isfinite(q) or not 0 < q <= 1e12:
            raise InputError(f"{symbol}: quantity must be a positive finite number.")
        kind = row.get("declared_kind", "Auto")
        if kind not in {"Auto", "Stock", "ETF"}:
            raise InputError("Only stocks and ETFs are supported.")
        if symbol in merged:
            if merged[symbol]["declared_kind"] != kind:
                raise InputError(f"Conflicting types for {symbol}.")
            merged[symbol]["quantity"] += q
        else:
            merged[symbol] = {"symbol": symbol, "quantity": q, "declared_kind": kind}
    return list(merged.values())
