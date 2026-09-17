"""FRED DGS10 is percent, not the Cboe TNX index's ten-times display unit."""
import csv
from datetime import timedelta
from io import StringIO

from data_quality import error_reason, get_response, observation, utc_now

URL = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10'


def parse_treasury_csv(text, now=None):
    rows = list(csv.DictReader(StringIO(text.lstrip('\ufeff'))))
    if not rows or 'observation_date' not in rows[0] or 'DGS10' not in rows[0]:
        raise ValueError('unexpected FRED CSV schema')
    rows = [r for r in rows if r['DGS10'].strip() not in {'', '.'}]
    if not rows:
        raise ValueError('no published yield')
    row = max(rows, key=lambda r: r['observation_date'])
    return observation('BOND_10Y', row['DGS10'], 'FRED / Federal Reserve DGS10',
                       row['observation_date'], source_url=URL, unit='%', now=now,
                       details={'frequency': 'daily; publication may lag the observation'})


def fetch_10y_treasury_yield():
    try:
        start = (utc_now().date() - timedelta(days=20)).isoformat()
        result = parse_treasury_csv(get_response(f'{URL}&cosd={start}', browser=True).text)
        if result['status'] == 'valid':
            return result
        reason = result['reason']
    except Exception as exc:
        reason = error_reason(exc)
    from data_fetchers import fetch_yf_price
    fallback = fetch_yf_price('^TNX')
    fallback.setdefault('details', {})['fallback_reason'] = f'FRED unavailable: {reason}'
    return fallback
