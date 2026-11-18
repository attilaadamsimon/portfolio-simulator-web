from io import BytesIO

import pytest

from portfolio_sim.imports import InputError, inspect_csv, parse_holdings, quantity, validate_holdings


@pytest.mark.parametrize("raw,decimal,identifier,shares", [
    (b'Ticker,Quantity,Asset Type\nAAPL,10.5,Stock\n', '.', 'AAPL', 10.5),
    ('ISIN;Stück;Wertpapiertyp\nIE00BK5BQT80;20,75;ETF\n'.encode(), ',', 'IE00BK5BQT80', 20.75),
    (b'Instrument,Quantity,Description\nMSFT,5,Microsoft\n', '.', 'MSFT', 5),
    ('sep=;\nSymbol;Anzahl;Name\nAAPL;1.234,56;Apple\n'.encode('cp1252'), ',', 'AAPL', 1234.56),
    (b'Symbol\tShares\nAAPL\t1,234.56\n', '.', 'AAPL', 1234.56),
])
def test_holdings_layouts(raw, decimal, identifier, shares):
    holding = parse_holdings(raw, decimal=decimal)['holdings'][0]
    assert holding['identifier'] == identifier
    assert holding['quantity'] == shares


def test_isin_needs_explicit_listing():
    h = parse_holdings(b'ISIN,Quantity\nIE00BK5BQT80,10\n')['holdings'][0]
    assert h['symbol'] == ''


def test_custom_mapping_and_duplicate_aggregation():
    result = parse_holdings(b'ID,Units Held\nAAPL,2\nAAPL,3\n', {'identifier':'ID','quantity':'Units Held'})
    assert len(result['holdings']) == 1
    assert result['holdings'][0]['quantity'] == 5


@pytest.mark.parametrize('raw', [
    b'Activity Date,Instrument,Quantity,Trans Code\n2026-01-01,AAPL,5,Buy\n',
    b'ISIN;Quantity;Type\nUS0378331005;2;Kauf\n',
    b'Instrument,Quantity,Transaction Type\nAAPL,2,BUY\n',
])
def test_transaction_reports_are_rejected(raw):
    with pytest.raises(InputError, match='transaction|transactions'):
        parse_holdings(raw)


def test_excluded_assets_and_zero_are_counted():
    result = parse_holdings(b'Symbol,Quantity,Type\nAAPL,2,Stock\nAAPL261120C00200000,1,Option\nUSD,20,Cash\nMSFT,0,Stock\n')
    assert result['skipped'] == 3
    assert len(result['holdings']) == 1


@pytest.mark.parametrize('value', ['NaN','inf','-1','1.234,56','1,23.45','', '1e1000'])
def test_bad_or_misformatted_quantities(value):
    with pytest.raises(InputError):
        quantity(value, '.')


@pytest.mark.parametrize('raw', [b'  ', b'Symbol,Symbol\nAAPL,2\n', b'Symbol,Quantity\nAAPL,2,extra\n', b'Symbol,Quantity\nAAPL\n'])
def test_malformed_csv(raw):
    with pytest.raises(InputError):
        inspect_csv(raw)


def test_unknown_type_is_not_silently_stock():
    with pytest.raises(InputError, match='Unknown asset type'):
        parse_holdings(b'Symbol,Quantity,Type\nAAA,5,Structured product\n')


@pytest.mark.parametrize('shares', [True, float('nan'), float('inf'), 0, -1, '2'])
def test_api_quantities_validated(shares):
    with pytest.raises(InputError):
        validate_holdings([{'symbol':'AAPL','quantity':shares}])
