"""AAII official XLS, with the official current survey page for newer releases."""
from datetime import datetime, timedelta
from io import BytesIO
import json
import os
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import pandas as pd
import requests

from data_quality import SourceUnavailable, error_reason, get_response, invalid, number, observation

PAGE = 'https://www.aaii.com/sentimentsurvey'
XLS = 'https://www.aaii.com/files/surveys/sentiment.xls'
FIRECRAWL_API = 'https://api.firecrawl.dev/v2/scrape'


def parse_aaii_xls(content, now=None):
    sheet = pd.read_excel(BytesIO(content), header=None, engine='xlrd')
    if not all(label in sheet.iloc[:6].to_string() for label in ('Date', 'Bullish', 'Neutral', 'Bearish')):
        raise ValueError('unexpected AAII workbook schema')
    rows = [row for _, row in sheet.iterrows() if isinstance(row.iloc[0], datetime)
            and all(pd.notna(row.iloc[i]) for i in (1, 2, 3))]
    row = max(rows, key=lambda r: r.iloc[0])
    release = row.iloc[0].date().isoformat()
    bull, neutral, bear = (number(row.iloc[i]) * 100 for i in (1, 2, 3))
    return observation('AAII', bull - bear, 'AAII official historical XLS', release, source_url=XLS,
                       now=now, unit='pp', details={'bull': bull, 'bear': bear, 'neutral': neutral,
                       'release_date': release, 'date_kind': 'Reported Date in official XLS',
                       'survey_week_ending': None, 'frequency': 'weekly'})


def parse_aaii_page(html, now=None):
    soup = BeautifulSoup(html, 'html.parser')
    text = soup.get_text(' ', strip=True)
    match = re.search(
        r"This week's results\s*Week ending\s+([A-Za-z]+ \d{1,2}, \d{4})\s+"
        r"Bullish\s+([\d.]+)%.*?Neutral\s+([\d.]+)%.*?Bearish\s+([\d.]+)%", text, re.S)
    if not match:
        raise ValueError('current weekly AAII result missing')
    ending = datetime.strptime(match[1], '%B %d, %Y').date()
    releases = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text())
            for entry in data if isinstance(data, list) else [data]:
                if entry.get('@type') == 'WebPage' and entry.get('url', '').rstrip('/') == PAGE:
                    releases.extend(str(entry.get(field, ''))[:10]
                                    for field in ('datePublished', 'dateModified'))
        except (ValueError, AttributeError):
            continue
    # Do not substitute the fetch date for the weekly release date.
    expected_release = (ending + timedelta(days=1)).isoformat()
    if ending.weekday() != 2 or expected_release not in releases:
        raise ValueError('AAII release metadata does not match survey week')
    bull, neutral, bear = map(number, match.group(2, 3, 4))
    return observation('AAII', bull - bear, 'AAII official weekly survey', expected_release,
                       source_url=PAGE, now=now, unit='pp', details={
                       'bull': bull, 'bear': bear, 'neutral': neutral, 'release_date': expected_release,
                       'survey_week_ending': ending.isoformat(), 'frequency': 'weekly',
                       'publication_evidence': 'official page dateModified/datePublished + weekly period'})


def fetch_aaii_via_firecrawl(api_key):
    """Optional transport for the public official page, never AI extraction or cached input."""
    response = requests.post(
        FIRECRAWL_API, headers={'Authorization': f'Bearer {api_key}'},
        json={'url': PAGE, 'formats': ['rawHtml'], 'onlyMainContent': False,
              'maxAge': 0, 'timeout': 45000},
        timeout=(10, 55), allow_redirects=False)
    if response.status_code != 200:
        raise SourceUnavailable(f'AAII fallback HTTP {response.status_code}')
    payload = response.json()
    data = payload.get('data') or {}
    metadata = data.get('metadata') or {}
    origin = urlparse(metadata.get('sourceURL', ''))
    if (payload.get('success') is not True or metadata.get('statusCode') != 200
            or origin.scheme != 'https' or origin.hostname != 'www.aaii.com'
            or origin.path.rstrip('/') != '/sentimentsurvey'):
        raise SourceUnavailable('AAII fallback did not confirm the official source')
    html = data.get('rawHtml')
    if not isinstance(html, str) or not html.strip():
        raise SourceUnavailable('AAII fallback returned no raw HTML')
    result = parse_aaii_page(html)
    result['source'] = 'AAII official weekly survey (via Firecrawl)'
    result['details']['retrieval_method'] = 'Firecrawl rawHtml; maxAge=0; no AI extraction'
    return result


def fetch_aaii_bull_bear_diff():
    candidates, errors = [], []
    page_valid = False
    for url, parser, binary in [(XLS, parse_aaii_xls, True), (PAGE, parse_aaii_page, False)]:
        try:
            response = get_response(url, browser=True)
            result = parser(response.content if binary else response.text)
            if result['status'] == 'valid':
                candidates.append(result)
                page_valid = page_valid or url == PAGE
            else:
                errors.append(result['reason'])
        except Exception as exc:
            errors.append(error_reason(exc))
    # The workbook can lag the current release. Try a fresh official page via
    # the optional transport whenever the direct page was unavailable.
    api_key = os.environ.get('FIRECRAWL_API_KEY', '').strip()
    if api_key and not page_valid:
        try:
            result = fetch_aaii_via_firecrawl(api_key)
            if result['status'] == 'valid':
                candidates.append(result)
            else:
                errors.append(result['reason'])
        except Exception as exc:
            errors.append(error_reason(exc))
    if not candidates:
        return invalid('AAII official sources', '; '.join(errors), source_url=PAGE)
    chosen = max(candidates, key=lambda r: r['details']['release_date'])
    for other in candidates:
        if other['data_date'] == chosen['data_date'] and abs(other['value'] - chosen['value']) > 0.3:
            return invalid('AAII official sources', 'official sources disagree for same release',
                           chosen['data_date'], PAGE)
    chosen['details']['source_checks'] = len(candidates)
    if errors:
        chosen['details']['source_warnings'] = errors
    return chosen
