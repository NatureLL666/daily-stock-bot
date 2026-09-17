"""CBOE TOTAL (not equity/index) ratio with the source's selectedDate."""
import json

from bs4 import BeautifulSoup

from data_quality import completed_sessions, error_reason, get_response, invalid, observation

URL = 'https://www.cboe.com/markets/us/options/market-statistics/daily'


def parse_put_call(html, expected_date, now=None):
    soup = BeautifulSoup(html, 'html.parser')
    chunks = []
    for script in soup.find_all('script'):
        text = script.get_text().strip()
        prefix = 'self.__next_f.push('
        if text.startswith(prefix):
            try:
                part = json.loads(text[len(prefix):text.rfind(')')])
                if len(part) > 1 and isinstance(part[1], str):
                    chunks.append(part[1])
            except (ValueError, TypeError):
                continue
    # Next.js can split one JSON object across multiple flight script tags.
    stream = ''.join(chunks)
    marker = stream.find('"optionsData"')
    if marker < 0:
        raise ValueError('CBOE dated statistics object missing')
    data, _ = json.JSONDecoder().raw_decode(stream[marker - 1:])
    actual_date = data.get('selectedDate')
    if actual_date != expected_date:
        raise ValueError('CBOE returned a different date than requested')
    ratios = [r for r in data['optionsData']['ratios'] if r['name'] == 'TOTAL PUT/CALL RATIO']
    if len(ratios) != 1:
        raise ValueError('TOTAL PUT/CALL RATIO missing or ambiguous')
    return observation('PUT_CALL', ratios[0]['value'], 'CBOE TOTAL PUT/CALL RATIO', actual_date,
                       source_url=f'{URL}?dt={actual_date}', now=now,
                       details={'ratio_type': 'TOTAL'})


def fetch_put_call_ratio():
    errors = []
    for day in reversed(completed_sessions()[-5:]):
        day = day.isoformat()
        try:
            result = parse_put_call(get_response(f'{URL}?dt={day}').text, day)
            if result['status'] == 'valid':
                result['details']['lookback_attempts'] = len(errors)
                return result
            errors.append(f'{day}: {result["reason"]}')
        except Exception as exc:
            errors.append(f'{day}: {error_reason(exc)}')
    return invalid('CBOE TOTAL PUT/CALL RATIO', '; '.join(errors), source_url=URL)
