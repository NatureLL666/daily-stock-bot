"""Shared validation and HTTP handling; fetchers remain in their original modules."""
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
import math
import re

import pandas_market_calendars as mcal
import requests
from curl_cffi import requests as browser_requests

UTC = timezone.utc
UNAVAILABLE = '⚠️ 数据不可用'
NAAIM_PUBLIC_URL = 'https://index.naaim.org/embeddable/table'
# Public NAAIM has a three-calendar-month delay, plus a weekly publication buffer.
NAAIM_REFERENCE_MAX_AGE = 110
RANGES = {
    'BOND_10Y': (0, 25), 'BOND_3M': (0, 25), 'DXY': (20, 300),
    'VIX': (0, 200), 'SKEW': (50, 400), 'PUT_CALL': (0, 10),
    'CNN': (0, 100), 'RSI': (0, 100), 'ABOVE_200_DAYS': (0, 100),
    'NAAIM': (-200, 200), 'AAII': (-100, 100), 'BTC': (-100, 1000),
    'HYG': (0, 10000), 'IWM': (0, 100000), 'SOXX': (0, 100000),
    'RISK_RATIO': (0, 1000),
}
NO_ZERO = {'BOND_10Y', 'BOND_3M', 'DXY', 'VIX', 'SKEW', 'PUT_CALL',
           'NAAIM', 'HYG', 'IWM', 'SOXX', 'RISK_RATIO'}


class SourceUnavailable(RuntimeError):
    """A safe, locally generated explanation; contains no response body or secrets."""


def utc_now():
    return datetime.now(UTC)


def number(value):
    """Accept a whole numeric field, never digits embedded in an error string."""
    if isinstance(value, bool) or value is None:
        raise ValueError('missing or non-numeric value')
    if isinstance(value, str):
        value = value.strip()
        if not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)%?', value):
            raise ValueError('non-numeric value')
        value = value.removesuffix('%')
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('non-finite value')
    return result


def invalid(source, reason, data_date=None, source_url='', **details):
    def clean(value):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [clean(v) for v in value]
        return value
    return {'value': None, 'source': source, 'source_url': source_url,
            'data_date': data_date, 'status': 'invalid', 'reason': reason,
            'fetched_at': utc_now().isoformat(), 'details': clean(details)}


def observation(key, value, source, data_date, *, source_url='', details=None,
                now=None, max_age_days=None, unit=''):
    now = now or utc_now()
    info = dict(details or {})
    dated = None
    try:
        dated = date.fromisoformat(str(data_date))
        age = (now.date() - dated).days
        limit = max_age_days if max_age_days is not None else (14 if key in {'AAII', 'NAAIM'} else 7)
        if age < 0:
            raise ValueError('future data date')
        if age > limit:
            raise ValueError(f'stale data: {age} days old (limit {limit})')
        if not source or not source_url:
            raise ValueError('missing source attribution')
        val = number(value)
        low, high = RANGES.get(key, (0, 1e15))
        if not low <= val <= high or (key in NO_ZERO and val == 0):
            raise ValueError('value outside validity range or zero placeholder')
        if key == 'AAII':
            bull, bear, neutral = (number(info[k]) for k in ('bull', 'bear', 'neutral'))
            if not all(0 <= v <= 100 for v in (bull, bear, neutral)):
                raise ValueError('invalid AAII percentages')
            if abs(bull + bear + neutral - 100) > 0.3 or abs(bull - bear - val) > 0.15:
                raise ValueError('AAII components do not match spread')
            release = date.fromisoformat(info['release_date'])
            if release > now.date() or release < dated or (release - dated).days > 7:
                raise ValueError('invalid AAII publication date')
        if key in {'HYG', 'IWM', 'SOXX'}:
            ma = number(info['ma20'])
            if ma <= 0 or info.get('trend') != ('Above' if val > ma else 'Below'):
                raise ValueError('invalid MA20 comparison')
        if key == 'RISK_RATIO':
            prev = number(info['previous_ratio'])
            if prev <= 0 or info.get('trend') != ('Up' if val > prev else 'Down'):
                raise ValueError('invalid ratio comparison')
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return invalid(source, str(exc), dated.isoformat() if dated else None, source_url,
                       **info)
    return {'value': val, 'source': source, 'source_url': source_url,
            'data_date': dated.isoformat(), 'status': 'valid', 'reason': '',
            'fetched_at': now.isoformat(), 'unit': unit, 'details': info}


def delayed_naaim(value, source, data_date, *, source_url, details=None, now=None):
    """A real public observation kept for reference, never eligible for today's vote."""
    now = now or utc_now()
    if source_url != NAAIM_PUBLIC_URL:
        return invalid(source, 'unverified delayed NAAIM source', data_date, source_url)
    result = observation('NAAIM', value, source, data_date, source_url=source_url,
                         details=details, now=now, max_age_days=NAAIM_REFERENCE_MAX_AGE)
    if result['status'] == 'valid':
        age = (now.date() - date.fromisoformat(result['data_date'])).days
        result['status'] = 'delayed'
        result['reason'] = '公开数据延迟约三个月，仅供历史参考，不参与当前多空统计'
        result['details'].update({'delay_days': age, 'eligible_for_summary': False,
                                  'access': 'public_delayed', 'release_date': None})
    return result


def validate_result(key, result, now=None):
    if not isinstance(result, dict):
        return invalid('unverified', 'fetcher did not return a dated observation')
    if result.get('status') == 'delayed' and key == 'NAAIM':
        return delayed_naaim(result.get('value'), result.get('source'), result.get('data_date'),
                             source_url=result.get('source_url', ''), details=result.get('details'), now=now)
    if result.get('status') != 'valid':
        return {**result, 'value': None, 'status': 'invalid'}
    return observation(key, result.get('value'), result.get('source'), result.get('data_date'),
                       source_url=result.get('source_url', ''), details=result.get('details'),
                       now=now, unit=result.get('unit', ''))


def error_reason(exc):
    """No exception URLs/headers in logs: they may contain credentials."""
    response = getattr(exc, 'response', None)
    if isinstance(exc, SourceUnavailable):
        return str(exc)
    if response is not None:
        return f'HTTP {response.status_code}'
    return type(exc).__name__


def get_response(url, *, browser=False):
    # curl_cffi sets a matching browser User-Agent itself. Overriding it with the
    # generic Mozilla/5.0 makes CNN/AAII reject otherwise valid public requests.
    headers = {'Accept': 'application/json,text/html,*/*'}
    if 'cnn.io/' in url:
        headers['Referer'] = 'https://www.cnn.com/'
    if browser:
        response = browser_requests.get(url, headers=headers, impersonate='chrome', timeout=25)
    else:
        response = requests.get(url, headers={**headers, 'User-Agent': 'Mozilla/5.0'}, timeout=(10, 25))
        if response.status_code in {202, 403, 418}:
            response = browser_requests.get(url, headers=headers, impersonate='chrome', timeout=25)
    response.raise_for_status()
    if response.status_code != 200 or not response.content:
        raise SourceUnavailable('empty response or browser challenge')
    if b'Pardon Our Interruption' in response.content[:8192]:
        raise SourceUnavailable('provider bot-check page (HTTP 200); no market data')
    return response


@lru_cache(maxsize=32)
def _sessions(day):
    end = date.fromisoformat(day)
    return mcal.get_calendar('NYSE').schedule(start_date=end - timedelta(days=25), end_date=end)


def completed_sessions(now=None):
    now = now or utc_now()
    schedule = _sessions(now.date().isoformat())
    # Allow daily providers 30 minutes after the close before accepting today's bar.
    return [d.date() for d, row in schedule.iterrows()
            if row['market_close'].to_pydatetime() + timedelta(minutes=30) <= now]


def latest_session(now=None):
    return completed_sessions(now)[-1]
