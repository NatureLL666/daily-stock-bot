"""S&P 500 breadth from the dated public INDEX:S5TH daily-bar JSON."""
from datetime import datetime
import json

from bs4 import BeautifulSoup

from data_quality import UTC, error_reason, get_response, invalid, latest_session, observation

URL = 'https://www.tradingview.com/symbols/INDEX-S5TH/'


def parse_above_200(html, now=None):
    soup = BeautifulSoup(html, 'html.parser')
    matches = []

    def walk(node):
        if isinstance(node, dict):
            if node.get('pro_symbol') == 'INDEX:S5TH' and 'daily_bar' in node:
                matches.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for script in soup.select('script[type="application/prs.init-data+json"]'):
        walk(json.loads(script.get_text()))
    if len(matches) != 1 or matches[0].get('short_description') != 'S&P 500 Stocks Above 200-Day Average':
        raise ValueError('S5TH dated quote missing or wrong breadth series')
    bar = matches[0]['daily_bar']
    day = datetime.fromtimestamp(float(bar['time']), UTC).date()
    if day != latest_session(now):
        return invalid('TradingView INDEX:S5TH', 'breadth bar is not the latest completed session',
                       day.isoformat(), URL)
    return observation('ABOVE_200_DAYS', bar['close'], 'TradingView INDEX:S5TH', day.isoformat(),
                       source_url=URL, unit='%', now=now,
                       details={'universe': 'S&P 500', 'symbol': 'INDEX:S5TH', 'frequency': 'daily'})


def fetch_above_200_days_average():
    try:
        return parse_above_200(get_response(URL, browser=True).text)
    except Exception as exc:
        return invalid('TradingView INDEX:S5TH', error_reason(exc), source_url=URL)
