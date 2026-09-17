"""CNN's public JSON, retaining its own timestamp."""
from datetime import datetime
from zoneinfo import ZoneInfo

from data_quality import UTC, error_reason, get_response, invalid, observation, utc_now

URL = 'https://production.dataviz.cnn.io/index/fearandgreed/graphdata'


def parse_fear_greed(data, now=None):
    now = now or utc_now()
    point = data['fear_and_greed']
    timestamp = datetime.fromisoformat(point['timestamp'].replace('Z', '+00:00'))
    if timestamp.tzinfo is None or timestamp.astimezone(UTC) > now:
        raise ValueError('missing timezone or future CNN timestamp')
    day = timestamp.astimezone(ZoneInfo('America/New_York')).date().isoformat()
    return observation('CNN', point['score'], 'CNN Fear & Greed JSON', day, source_url=URL,
                       now=now, details={'timestamp': point['timestamp'], 'rating': point.get('rating')})


def fetch_fear_greed_meter():
    try:
        return parse_fear_greed(get_response(URL, browser=True).json())
    except Exception as exc:
        return invalid('CNN Fear & Greed JSON', error_reason(exc), source_url=URL)
