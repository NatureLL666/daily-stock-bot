"""Dated Yahoo prices and the original technical calculations."""
import csv
from datetime import datetime, timedelta
from functools import lru_cache
from io import StringIO
from pathlib import Path

import yfinance as yf
import pandas_market_calendars as mcal

from data_quality import (error_reason, get_response, invalid, latest_session,
                          number, observation, utc_now)

CACHE_DIR = Path(__file__).resolve().parent / '.cache' / 'yfinance'
CACHE_DIR.mkdir(parents=True, exist_ok=True)
yf.set_tz_cache_location(str(CACHE_DIR))


@lru_cache(maxsize=32)
def history(ticker, period='3mo', auto_adjust=True):
    data = yf.Ticker(ticker).history(period=period, auto_adjust=auto_adjust, timeout=20)
    if data.empty:
        raise ValueError('no Yahoo history')
    cutoff = utc_now().date() - timedelta(days=1) if ticker == 'BTC-USD' else latest_session()
    data = data.loc[[d.date() <= cutoff for d in data.index]]
    if data.empty or data.index[-1].date() != cutoff:
        raise ValueError('latest completed session missing')
    if data.index.has_duplicates or not data.index.is_monotonic_increasing:
        raise ValueError('duplicate or unordered daily bars')
    if ticker in {'HYG', 'IWM', 'SOXX', 'XLY', 'XLP', '^GSPC', '^NDX'}:
        expected = mcal.get_calendar('NYSE').valid_days(data.index[0].date(), cutoff)
        if [d.date() for d in data.index] != [d.date() for d in expected]:
            raise ValueError('missing trading sessions in calculation window')
    if any(number(v) <= 0 for v in data['Close']):
        raise ValueError('invalid close in lookback window')
    return data


def yahoo_url(ticker):
    from urllib.parse import quote
    return f'https://finance.yahoo.com/quote/{quote(ticker, safe="")}/history/'


def fetch_yf_price(ticker, correction=1.0):
    key = {'^TNX': 'BOND_10Y', '^IRX': 'BOND_3M', '^VIX': 'VIX', 'DX-Y.NYB': 'DXY'}.get(ticker, ticker)
    url = yahoo_url(ticker)
    try:
        data = history(ticker, '1mo')
        # Yahoo ^TNX already uses percent; no guessed division by ten.
        value = number(data['Close'].iloc[-1]) * correction
        return observation(key, value, f'Yahoo Finance ({ticker})', data.index[-1].date().isoformat(),
                           source_url=url, unit='%' if key.startswith('BOND') else '')
    except Exception as exc:
        return invalid(f'Yahoo Finance ({ticker})', error_reason(exc), source_url=url)


def fetch_yf_trend(ticker):
    url = yahoo_url(ticker)
    try:
        data = history(ticker, '2mo')
        if len(data) < 20:
            raise ValueError('fewer than 20 closes')
        value = number(data['Close'].iloc[-1])
        ma20 = number(data['Close'].rolling(20).mean().iloc[-1])
        return observation(ticker, value, f'Yahoo Finance ({ticker}, adjusted close)',
                           data.index[-1].date().isoformat(), source_url=url,
                           details={'ma20': ma20, 'trend': 'Above' if value > ma20 else 'Below'})
    except Exception as exc:
        return invalid(f'Yahoo Finance ({ticker})', error_reason(exc), source_url=url)


def fetch_bitcoin_trend():
    url = yahoo_url('BTC-USD')
    try:
        data = history('BTC-USD', '5d')
        if len(data) < 2 or (data.index[-1].date() - data.index[-2].date()).days != 1:
            raise ValueError('missing adjacent BTC daily bars')
        value = (data['Close'].iloc[-1] / data['Close'].iloc[-2] - 1) * 100
        return observation('BTC', value, 'Yahoo Finance (BTC-USD)', data.index[-1].date().isoformat(),
                           source_url=url, unit='%', details={'period': 'completed UTC day',
                           'previous_date': data.index[-2].date().isoformat()})
    except Exception as exc:
        return invalid('Yahoo Finance (BTC-USD)', error_reason(exc), source_url=url)


def fetch_risk_on_off_ratio():
    url = yahoo_url('XLY')
    try:
        xly, xlp = history('XLY', '1mo', False), history('XLP', '1mo', False)
        if list(xly.index[-2:]) != list(xlp.index[-2:]) or min(len(xly), len(xlp)) < 2:
            raise ValueError('XLY/XLP sessions do not align')
        value = number(xly['Close'].iloc[-1]) / number(xlp['Close'].iloc[-1])
        previous = number(xly['Close'].iloc[-2]) / number(xlp['Close'].iloc[-2])
        return observation('RISK_RATIO', value, 'Yahoo Finance (XLY/XLP)',
                           xly.index[-1].date().isoformat(), source_url=url,
                           details={'previous_ratio': previous, 'trend': 'Up' if value > previous else 'Down',
                                    'xlp_source_url': yahoo_url('XLP')})
    except Exception as exc:
        return invalid('Yahoo Finance (XLY/XLP)', error_reason(exc), source_url=url)


def fetch_rsi_index():
    url = yahoo_url('^GSPC')
    try:
        data = history('^GSPC', '2mo')
        if len(data) <= 14:
            raise ValueError('insufficient RSI history')
        delta = data['Close'].diff()
        gain = delta.where(delta > 0, 0).ewm(com=13, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(com=13, adjust=False).mean()
        value = (100 - 100 / (1 + gain / loss)).iloc[-1]
        return observation('RSI', value, 'Yahoo Finance (^GSPC), original RSI(14)',
                           data.index[-1].date().isoformat(), source_url=url)
    except Exception as exc:
        return invalid('Yahoo Finance (^GSPC)', error_reason(exc), source_url=url)


def parse_cboe_csv(text, key, column, url, now=None):
    rows = list(csv.DictReader(StringIO(text.lstrip('\ufeff'))))
    if not rows or 'DATE' not in rows[0] or column not in rows[0]:
        raise ValueError('unexpected CBOE CSV schema')
    row = max(rows, key=lambda r: datetime.strptime(r['DATE'], '%m/%d/%Y').date())
    day = datetime.strptime(row['DATE'], '%m/%d/%Y').date().isoformat()
    return observation(key, row[column], 'CBOE daily CSV', day, source_url=url, now=now)


def fetch_cboe_index(key, column):
    url = f'https://cdn.cboe.com/api/global/us_indices/daily_prices/{key}_History.csv'
    try:
        return parse_cboe_csv(get_response(url).text, key, column, url)
    except Exception as exc:
        return invalid('CBOE daily CSV', error_reason(exc), source_url=url)


def fetch_full_market_data():
    results = {}
    for ticker, prefix in [('^GSPC', 'SPX'), ('^NDX', 'NDX')]:
        try:
            data = history(ticker, '1mo', False)
            row = data.iloc[-1]
            if not number(row['Low']) <= min(number(row['Open']), number(row['Close'])) <= max(number(row['Open']), number(row['Close'])) <= number(row['High']):
                raise ValueError('inconsistent OHLC range')
            for field in ('Open', 'High', 'Low', 'Close', 'Volume'):
                key = f'{prefix}_{field}'
                value = number(row[field])
                if value <= 0:
                    raise ValueError('invalid OHLCV')
                results[key] = observation(key, value, f'Yahoo Finance ({ticker})',
                                          data.index[-1].date().isoformat(), source_url=yahoo_url(ticker))
        except Exception as exc:
            for field in ('Open', 'High', 'Low', 'Close', 'Volume'):
                results[f'{prefix}_{field}'] = invalid(f'Yahoo Finance ({ticker})', error_reason(exc),
                                                     source_url=yahoo_url(ticker))
    return results


def fetch_market_info():
    messages = []
    for ticker, name in [('^GSPC', 'S&P 500'), ('^NDX', 'Nasdaq 100')]:
        try:
            data = history(ticker, '1mo', False)
            current, previous = (number(v) for v in data['Close'].iloc[-2:][::-1])
            change = (current / previous - 1) * 100
            messages.append(f'{name}: {current:,.2f} ({change:+.2f}%) | {data.index[-1].date()} | Yahoo Finance')
        except Exception:
            messages.append(f'{name}: ⚠️ 数据不可用')
    return '\n'.join(messages)


def fetch_short_term_yield():
    return fetch_yf_price('^IRX')
