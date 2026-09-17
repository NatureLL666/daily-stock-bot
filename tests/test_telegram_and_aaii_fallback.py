from datetime import datetime, timezone
from pathlib import Path
import json

import pytest
import requests

import aaii_index as aaii
import data_quality as dq
import main
import telegram_push as tg
import utils
from config import INDICATORS

NOW = datetime(2026, 9, 17, 14, 0, tzinfo=timezone.utc)
FIX = Path(__file__).parent / 'fixtures'
FAKE_TOKEN = '123456789:' + 'synthetic-test-token-never-use-this'
FAKE_CHAT = '123456'


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for module in (dq, tg, utils):
        monkeypatch.setattr(module, 'utc_now', lambda: NOW)
    for name in ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID', 'FIRECRAWL_API_KEY', 'DISCORD_WEBHOOK_URL'):
        monkeypatch.delenv(name, raising=False)
    # Tests must never use real credentials or send real notifications.
    monkeypatch.setattr(main, 'load_dotenv', lambda *a, **kw: None)
    monkeypatch.setattr(requests, 'post', lambda *a, **kw: pytest.fail('unexpected live request'))


class Response:
    def __init__(self, payload=None, status=200):
        self.status_code = status
        self.payload = payload

    def json(self):
        return self.payload


def configure_telegram(monkeypatch):
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', FAKE_TOKEN)
    monkeypatch.setenv('TELEGRAM_CHAT_ID', FAKE_CHAT)


def aa_payload(html=None, url=aaii.PAGE, status=200):
    return {'success': True, 'data': {
        'metadata': {'sourceURL': url, 'statusCode': status},
        'rawHtml': html if html is not None else (FIX / 'aaii.html').read_text(),
    }}


def test_telegram_report_keeps_all_indicators_dates_and_exclusions():
    results = {key: dq.invalid('official source', 'fetch failed') for key in INDICATORS}
    results['AAII'] = aaii.parse_aaii_page((FIX / 'aaii.html').read_text())
    # Do not trust an upstream status flag for a placeholder value.
    results['BOND_10Y'] = dq.observation('BOND_10Y', 5, 'FRED', '2026-09-15', source_url='https://fred.stlouisfed.org')
    results['BOND_10Y']['value'] = 0
    messages = tg.build_telegram_messages(results, 'market', utils.calculate_summary(results))
    report = '\n'.join(messages)
    assert 'Valid Indicators: 1/15' in report
    assert 'AAII Bull 28.8%' in report and 'AAII Bear 53.3%' in report
    assert 'Spread -24.5pp' in report and '调查发布日期 2026-09-17' in report
    assert report.count('invalid | Excluded') == 14
    assert report.count('数据日期:') == 15
    for cfg in INDICATORS.values():
        assert cfg['name'] in report
    assert all(tg.utf16_length(message) <= 4096 for message in messages)


def test_long_report_splits_without_breaking_an_indicator():
    results = {key: dq.invalid('📈' * 180, '⚠️' * 300) for key in INDICATORS}
    messages = tg.build_telegram_messages(results, '📊' * 1000, utils.calculate_summary(results))
    assert len(messages) > 1
    assert all(tg.utf16_length(m) <= 4096 for m in messages)
    for cfg in INDICATORS.values():
        part = next(m for m in messages if cfg['name'] in m)
        assert '数据日期:' in part[part.index(cfg['name']):]


@pytest.mark.parametrize('configured', [None, 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID'])
def test_missing_telegram_config_skips_without_network(monkeypatch, configured):
    if configured:
        monkeypatch.setenv(configured, FAKE_TOKEN if configured.endswith('TOKEN') else FAKE_CHAT)
    assert tg.send_telegram({}, '', '') == 'skipped'


@pytest.mark.parametrize('token,chat', [(FAKE_TOKEN + '/sendMessage', FAKE_CHAT), (FAKE_TOKEN, '@someone')])
def test_telegram_rejects_malformed_config(monkeypatch, token, chat):
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', token)
    monkeypatch.setenv('TELEGRAM_CHAT_ID', chat)
    assert tg.send_telegram({}, '', '') == 'failed'


def test_successful_telegram_uses_bound_destination_plain_text_and_no_redirects(monkeypatch):
    configure_telegram(monkeypatch)
    sent = []

    def post(url, **kwargs):
        sent.append(kwargs)
        assert url.startswith('https://api.telegram.org/bot')
        assert kwargs['allow_redirects'] is False
        assert kwargs['json']['chat_id'] == int(FAKE_CHAT)
        assert 'parse_mode' not in kwargs['json']
        return Response({'ok': True, 'result': {'message_id': len(sent), 'chat': {'id': int(FAKE_CHAT)}}})

    monkeypatch.setattr(tg.requests, 'post', post)
    assert tg.send_telegram({}, '', utils.calculate_summary({})) == 'sent'
    assert sent


@pytest.mark.parametrize('response', [
    Response({'ok': False, 'description': FAKE_TOKEN}, 200),
    Response({'ok': True, 'result': {'message_id': 1, 'chat': {'id': 999}}}),
    Response({'ok': False, 'description': FAKE_TOKEN}, 401),
    Response(None, 302),
])
def test_failed_or_wrong_destination_response_never_claims_sent_or_leaks_secrets(monkeypatch, capsys, response):
    configure_telegram(monkeypatch)
    monkeypatch.setattr(tg.requests, 'post', lambda *a, **kw: response)
    assert tg.send_telegram({}, '', '') == 'failed'
    output = capsys.readouterr().out
    assert FAKE_TOKEN not in output and FAKE_CHAT not in output


def test_ambiguous_timeout_is_not_retried_and_token_url_stays_hidden(monkeypatch, capsys):
    configure_telegram(monkeypatch)
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        raise requests.Timeout('timeout at ' + url)

    monkeypatch.setattr(tg.requests, 'post', post)
    assert tg.send_telegram({}, '', '') == 'failed'
    assert len(calls) == 1
    assert FAKE_TOKEN not in capsys.readouterr().out


def test_main_preserves_local_data_when_notification_fails(monkeypatch, tmp_path):
    record = dq.observation('VIX', 20, 'CBOE', '2026-09-16', source_url='https://cdn.cboe.com')
    monkeypatch.setattr(utils, 'ROOT', tmp_path)
    monkeypatch.setattr(main, 'fetch_all_indices', lambda: {'VIX': record})
    monkeypatch.setattr(main.df, 'fetch_market_info', lambda: 'market')
    monkeypatch.setattr(main.df, 'fetch_full_market_data', lambda: {})
    monkeypatch.setattr(main.df, 'fetch_short_term_yield', lambda: dq.invalid('source', 'failed'))
    monkeypatch.setattr(main, 'send_telegram', lambda *a: 'failed')
    assert main.main() == 2
    assert (tmp_path / 'data/history.csv').exists()
    assert json.loads((tmp_path / 'data/latest.json').read_text())['counts']['valid'] == 1


def test_firecrawl_fetches_fresh_raw_official_html_and_preserves_release(monkeypatch):
    def post(url, **kwargs):
        assert url == aaii.FIRECRAWL_API
        assert kwargs['allow_redirects'] is False
        assert kwargs['json']['url'] == aaii.PAGE
        assert kwargs['json']['maxAge'] == 0
        assert kwargs['json']['formats'] == ['rawHtml']
        return Response(aa_payload())

    monkeypatch.setattr(aaii.requests, 'post', post)
    record = aaii.fetch_aaii_via_firecrawl('synthetic-firecrawl-key')
    assert record['status'] == 'valid'
    assert record['value'] == pytest.approx(-24.5)
    assert record['data_date'] == '2026-09-17'
    assert record['source_url'] == aaii.PAGE
    assert 'Firecrawl' in record['source']


@pytest.mark.parametrize('payload', [aa_payload(url='https://other.example/sentimentsurvey'),
                                    aa_payload(status=403), aa_payload(html=''),
                                    {'success': False}])
def test_firecrawl_cannot_substitute_another_source_or_empty_response(monkeypatch, payload):
    monkeypatch.setattr(aaii.requests, 'post', lambda *a, **kw: Response(payload))
    with pytest.raises(dq.SourceUnavailable):
        aaii.fetch_aaii_via_firecrawl('synthetic-firecrawl-key')


def test_firecrawl_bot_challenge_stays_invalid_without_leaking_key(monkeypatch):
    monkeypatch.setenv('FIRECRAWL_API_KEY', 'synthetic-firecrawl-key')
    monkeypatch.setattr(aaii, 'get_response', lambda *a, **kw: (_ for _ in ()).throw(dq.SourceUnavailable('bot-check')))
    monkeypatch.setattr(aaii.requests, 'post', lambda *a, **kw: Response(aa_payload(html='<title>Pardon Our Interruption</title>')))
    record = aaii.fetch_aaii_bull_bear_diff()
    assert record['status'] == 'invalid' and record['value'] is None
    assert 'synthetic-firecrawl-key' not in json.dumps(record)


def test_direct_valid_official_page_skips_paid_transport(monkeypatch):
    monkeypatch.setenv('FIRECRAWL_API_KEY', 'synthetic-firecrawl-key')

    def get(url, **kw):
        if url == aaii.XLS:
            raise dq.SourceUnavailable('unavailable XLS')
        return type('Page', (), {'text': (FIX / 'aaii.html').read_text()})()

    monkeypatch.setattr(aaii, 'get_response', get)
    record = aaii.fetch_aaii_bull_bear_diff()
    assert record['status'] == 'valid'
    assert record['source'] == 'AAII official weekly survey'


def test_valid_older_xls_does_not_hide_newer_fallback_release(monkeypatch):
    monkeypatch.setenv('FIRECRAWL_API_KEY', 'synthetic-firecrawl-key')
    older = dq.observation('AAII', 10, 'AAII XLS', '2026-09-10', source_url=aaii.XLS,
                           details={'bull': 40, 'neutral': 30, 'bear': 30, 'release_date': '2026-09-10'})

    def get(url, **kw):
        if url == aaii.XLS:
            return type('Workbook', (), {'content': b'file'})()
        raise dq.SourceUnavailable('bot-check')

    monkeypatch.setattr(aaii, 'get_response', get)
    monkeypatch.setattr(aaii, 'parse_aaii_xls', lambda *a: older)
    monkeypatch.setattr(aaii.requests, 'post', lambda *a, **kw: Response(aa_payload()))
    record = aaii.fetch_aaii_bull_bear_diff()
    assert record['data_date'] == '2026-09-17'
    assert record['value'] == pytest.approx(-24.5)


def test_original_page_publication_date_does_not_hide_modified_release():
    html = (FIX / 'aaii.html').read_text().replace('"dateModified":', '"datePublished": "2020-01-01", "dateModified":')
    assert aaii.parse_aaii_page(html)['data_date'] == '2026-09-17'


def test_fresh_transport_does_not_make_stale_survey_valid(monkeypatch):
    html = (FIX / 'aaii.html').read_text().replace('September 16, 2026', 'August 19, 2026').replace('2026-09-17', '2026-08-20')
    monkeypatch.setattr(aaii.requests, 'post', lambda *a, **kw: Response(aa_payload(html)))
    record = aaii.fetch_aaii_via_firecrawl('synthetic-firecrawl-key')
    assert record['status'] == 'invalid' and record['value'] is None
    assert record['data_date'] == '2026-08-20'
