"""The public NAAIM table is delayed; stale values must not vote."""
import csv
from datetime import datetime
from io import StringIO
import os
from pathlib import Path

from bs4 import BeautifulSoup

from data_quality import NAAIM_PUBLIC_URL, delayed_naaim, error_reason, get_response, invalid, observation

URL = NAAIM_PUBLIC_URL
SOURCE = 'NAAIM official weekly table (public delayed access)'


def parse_naaim_table(html, now=None):
    soup = BeautifulSoup(html, 'html.parser')
    rows = []
    for table in soup.find_all('table'):
        headers = table.get_text(' ', strip=True)
        if 'NAAIM Number' not in headers or 'Date' not in headers:
            continue
        for tr in table.find_all('tr'):
            cells = [td.get_text(' ', strip=True) for td in tr.find_all('td')]
            if len(cells) < 2:
                continue
            try:
                day = datetime.strptime(cells[0], '%m/%d/%Y').date()
            except ValueError:
                continue
            rows.append((day, cells[1]))
    if not rows:
        raise ValueError('dated NAAIM table missing')
    day, value = max(rows)
    result = delayed_naaim(value, SOURCE, day.isoformat(), source_url=URL, now=now,
                         details={'frequency': 'weekly', 'date_kind': 'survey observation',
                                  'release_date': None})
    if result['status'] == 'invalid':
        result['reason'] += '; invalid even for delayed public reference'
    return result


def parse_authorized_csv(text, now=None):
    """Optional user-supplied licensed export; never scraped from a paid endpoint."""
    rows = list(csv.DictReader(StringIO(text)))
    required = {'data_date', 'release_date', 'value'}
    if not rows or not required.issubset(rows[0]):
        raise ValueError('licensed CSV requires data_date, release_date, value')
    row = max(rows, key=lambda r: r['data_date'])
    release = datetime.strptime(row['release_date'], '%Y-%m-%d').date()
    from data_quality import utc_now
    today = (now or utc_now()).date()
    if not row['data_date'] <= release.isoformat() <= today.isoformat():
        raise ValueError('invalid licensed publication date')
    return observation('NAAIM', row['value'], 'NAAIM (user-supplied licensed export)',
                       row['data_date'], source_url='https://index.naaim.org/', now=now,
                       details={'release_date': release.isoformat(), 'frequency': 'weekly'})


def fetch_naaim_exposure_index():
    try:
        path = os.environ.get('NAAIM_CSV_PATH', '').strip()
        if path:
            return parse_authorized_csv(Path(path).read_text(encoding='utf-8-sig'))
        return parse_naaim_table(get_response(URL).text)
    except Exception as exc:
        return invalid(SOURCE, error_reason(exc), source_url=URL)
