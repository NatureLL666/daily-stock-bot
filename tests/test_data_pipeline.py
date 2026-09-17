from datetime import datetime, timezone
from pathlib import Path
import csv
import json

import pandas as pd
import pytest

import data_quality as dq
import data_fetchers as df
import utils
from config import INDICATORS
from aaii_index import parse_aaii_page, parse_aaii_xls
from above_200_days_average import parse_above_200
from fear_greed_index import parse_fear_greed
from naaim_index import parse_naaim_table, parse_authorized_csv
from put_call_ratio import parse_put_call
from treasury_yield import parse_treasury_csv

NOW = datetime(2026, 9, 17, 13, 25, tzinfo=timezone.utc)
FIX = Path(__file__).parent / 'fixtures'


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(dq, 'utc_now', lambda: NOW)
    monkeypatch.setattr(df, 'utc_now', lambda: NOW)
    monkeypatch.setattr(utils, 'utc_now', lambda: NOW)
    df.history.cache_clear()


def valid(key, value, day='2026-09-16', **details):
    return dq.observation(key, value, 'test source', day, source_url='https://example.com/data',
                          details=details)


@pytest.mark.parametrize('value', [None, '', 'N/A', 'Error 403', '抓取失败 0', 'None', 'NaN',
                                    float('nan'), float('inf'), True, '12 34', '4.2 garbage', '-1 error'])
def test_bad_values_cannot_vote(value):
    record = valid('BOND_10Y', value)
    assert record['status'] == 'invalid'
    assert record['value'] is None
    assert utils.direction('BOND_10Y', record) == 'Excluded'


@pytest.mark.parametrize('key,value', [('BOND_10Y', 0), ('BOND_10Y', 40.5), ('SKEW', 0),
                                       ('SKEW', 17), ('NAAIM', 0), ('PUT_CALL', 0),
                                       ('CNN', -1), ('RSI', 101), ('DXY', -1)])
def test_obvious_sentinels_are_invalid(key, value):
    assert valid(key, value)['status'] == 'invalid'


def test_real_negative_spread_and_zero_change_are_valid():
    record = valid('AAII', -1, '2026-09-17', bull=35, neutral=29, bear=36, release_date='2026-09-17')
    assert record['status'] == 'valid'
    assert valid('BTC', 0)['status'] == 'valid'
    assert valid('AAII', -1)['status'] == 'invalid'
    assert utils.get_indicator_status('AAII', (None, None, -1)) == dq.UNAVAILABLE
    assert utils.extract_numeric_value('-1') == '-1.0'


def test_dates_and_weekly_reuse():
    assert valid('VIX', 20, '2026-09-18')['status'] == 'invalid'
    assert valid('VIX', 20, '2026-09-01')['status'] == 'invalid'
    assert valid('NAAIM', 80, '2026-09-09')['status'] == 'valid'
    assert valid('NAAIM', 80, '2026-09-02')['status'] == 'invalid'
    assert valid('VIX', 20, None)['status'] == 'invalid'


@pytest.mark.parametrize('key,value,expected', [
    ('BOND_10Y', 3.5, 'Bull'), ('BOND_10Y', 4.5, 'Bear'), ('BOND_10Y', 4, 'Neutral'),
    ('VIX', 31, 'Bull'), ('VIX', 14, 'Bear'), ('VIX', 30, 'Neutral'),
    ('PUT_CALL', 1.01, 'Bull'), ('PUT_CALL', .79, 'Bear'), ('PUT_CALL', 1, 'Neutral'),
    ('BTC', 3.01, 'Bull'), ('BTC', -3.01, 'Bear'), ('BTC', -3, 'Neutral'),
    ('CNN', 45, 'Bull'), ('CNN', 55, 'Bear'), ('SKEW', 140, 'Bear'),
])
def test_original_signal_boundaries(key, value, expected):
    assert utils.direction(key, valid(key, value)) == expected


def test_trend_comparison_must_have_valid_inputs():
    assert valid('HYG', 80)['status'] == 'invalid'
    assert utils.direction('HYG', valid('HYG', 80, ma20=81, trend='Below')) == 'Bear'
    assert valid('HYG', 80, ma20=81, trend='Above')['status'] == 'invalid'
    assert valid('RISK_RATIO', 1.3, previous_ratio=None, trend='Up')['status'] == 'invalid'


def test_total_put_call_and_source_date():
    text = (FIX / 'put_call.html').read_text()
    record = parse_put_call(text, '2026-09-16', NOW)
    assert record['value'] == .98  # Equity is .69 in the same payload.
    assert record['data_date'] == '2026-09-16'
    with pytest.raises(ValueError, match='different date'):
        parse_put_call(text, '2026-09-17', NOW)


def test_put_call_backtracks_without_changing_actual_date(monkeypatch):
    import put_call_ratio as pc
    days = [datetime(2026, 9, d).date() for d in (15, 16)]
    monkeypatch.setattr(pc, 'completed_sessions', lambda: days)
    requested = []

    def get(url):
        requested.append(url)
        text = (FIX / 'put_call.html').read_text()
        if url.endswith('2026-09-16'):
            return type('Response', (), {'text': '<html>no published data</html>'})()
        return type('Response', (), {'text': text.replace('2026-09-16', '2026-09-15')})()

    monkeypatch.setattr(pc, 'get_response', get)
    record = pc.fetch_put_call_ratio()
    assert record['status'] == 'valid'
    assert record['data_date'] == '2026-09-15'
    assert record['details']['lookback_attempts'] == 1
    assert len(requested) == 2


def test_aaii_retains_release_and_survey_week():
    record = parse_aaii_page((FIX / 'aaii.html').read_text(), NOW)
    assert record['value'] == pytest.approx(-24.5)
    assert record['details']['bull'] == 28.8
    assert record['details']['bear'] == 53.3
    assert record['data_date'] == record['details']['release_date'] == '2026-09-17'
    assert record['details']['survey_week_ending'] == '2026-09-16'
    later = datetime(2026, 9, 20, tzinfo=timezone.utc)
    assert parse_aaii_page((FIX / 'aaii.html').read_text(), later)['data_date'] == '2026-09-17'


def test_aaii_xls_uses_reported_date_and_fraction_units(monkeypatch):
    sheet = pd.DataFrame([
        ['Date', 'Bullish', 'Neutral', 'Bearish'],
        [datetime(2026, 9, 10), .379501, .227147, .393352],
        ["Count '26", 52, 52, 52],
    ])
    monkeypatch.setattr(pd, 'read_excel', lambda *a, **kw: sheet)
    record = parse_aaii_xls(b'official-file', NOW)
    assert record['value'] == pytest.approx(-1.3851)
    assert record['data_date'] == '2026-09-10'
    assert record['status'] == 'valid'


def test_naaim_public_delay_is_excluded():
    record = parse_naaim_table((FIX / 'naaim.html').read_text(), NOW)
    assert record['status'] == 'delayed'
    assert record['value'] == 79.27
    assert record['data_date'] == '2026-06-10'
    assert record['details']['delay_days'] == 99
    assert utils.direction('NAAIM', record) == 'Excluded'


def test_authorized_naaim_preserves_dates_and_rejects_placeholder():
    text = 'data_date,release_date,value\n2026-09-16,2026-09-17,80.25\n'
    result = parse_authorized_csv(text, NOW)
    assert result['status'] == 'valid'
    assert result['details']['release_date'] == '2026-09-17'
    assert parse_authorized_csv(text.replace('80.25', '0'), NOW)['status'] == 'invalid'


def test_treasury_is_percent_and_skips_only_documented_holiday_blanks():
    record = parse_treasury_csv((FIX / 'fred.csv').read_text(), NOW)
    assert record['value'] == 5
    assert record['data_date'] == '2026-09-15'
    assert record['unit'] == '%'
    assert parse_treasury_csv('observation_date,DGS10\n2026-09-16,0\n', NOW)['status'] == 'invalid'
    assert parse_treasury_csv('observation_date,DGS10\n2026-09-16,50\n', NOW)['status'] == 'invalid'


def test_cboe_csv_latest_row_not_stale_fallback():
    record = df.parse_cboe_csv((FIX / 'skew.csv').read_text(), 'SKEW', 'SKEW', 'https://cboe.com/', NOW)
    assert record['value'] == 145.95
    text = 'DATE,SKEW\n09/15/2026,140\n09/16/2026,0\n'
    assert df.parse_cboe_csv(text, 'SKEW', 'SKEW', 'https://cboe.com/', NOW)['status'] == 'invalid'


def test_cnn_actual_timestamp_not_fetch_date():
    payload = json.loads((FIX / 'cnn.json').read_text())
    record = parse_fear_greed(payload, NOW)
    assert record['status'] == 'valid'
    assert record['data_date'] == '2026-09-17'
    payload['fear_and_greed']['timestamp'] = '2026-09-18T00:00:00Z'
    with pytest.raises(ValueError, match='future'):
        parse_fear_greed(payload, NOW)


def test_breadth_symbol_and_bar_date():
    text = (FIX / 'above200.html').read_text()
    record = parse_above_200(text, NOW)
    assert record['value'] == 50.09
    assert record['data_date'] == '2026-09-16'
    with pytest.raises(ValueError):
        parse_above_200(text.replace('INDEX:S5TH', 'INDEX:OTHER'), NOW)


def test_only_completed_bars_are_used(monkeypatch):
    frame = pd.DataFrame({'Close': [100, 101, 500]},
                         index=pd.date_range('2026-09-15', periods=3, tz='America/New_York'))
    monkeypatch.setattr(df.yf, 'Ticker', lambda _: type('Ticker', (), {'history': lambda self, **kw: frame})())
    actual = df.history('TEST')
    assert actual.index[-1].date().isoformat() == '2026-09-16'
    assert actual['Close'].iloc[-1] == 101


def test_stale_yahoo_data_is_rejected(monkeypatch):
    frame = pd.DataFrame({'Close': [100]}, index=pd.DatetimeIndex(['2026-09-15'], tz='America/New_York'))
    monkeypatch.setattr(df.yf, 'Ticker', lambda _: type('Ticker', (), {'history': lambda self, **kw: frame})())
    with pytest.raises(ValueError, match='latest completed'):
        df.history('TEST')


def test_market_calendar_includes_early_closes_and_holidays():
    # Day after Labor Day, before the close: Friday is the last completed session.
    assert dq.latest_session(datetime(2026, 9, 8, 13, 0, tzinfo=timezone.utc)).isoformat() == '2026-09-04'
    # Friday after Thanksgiving closes at 13:00 New York.
    assert dq.latest_session(datetime(2026, 11, 27, 18, 31, tzinfo=timezone.utc)).isoformat() == '2026-11-27'


def test_invalid_values_never_enter_counts_csv_or_discord(tmp_path):
    results = {key: dq.invalid('source', 'failed') for key in INDICATORS}
    results['DXY'] = valid('DXY', 100)
    results['SKEW'] = valid('SKEW', 145)
    # A forged valid flag still has to pass value/date validation.
    results['BOND_10Y'] = {**valid('BOND_10Y', 5), 'value': 0}
    counts = utils.summary_counts(results)
    assert counts == {'valid': 2, 'total': 15, 'bull': 1, 'neutral': 0, 'bear': 1, 'invalid': 13, 'delayed': 0}
    path = tmp_path / 'history.csv'
    path.write_text('Date,10Y_Yield,AAII_Diff\n2026-09-16,0,-1\n')
    original = path.read_bytes()
    row = utils.save_csv(results, market_data={}, short_yield=dq.invalid('source', 'failed'), path=path)
    assert row['10Y_Yield'] == row['NAAIM'] == row['AAII_Diff'] == ''
    assert row['10Y_Yield_status'] == 'invalid'
    assert b'\r\n' not in path.read_bytes()
    assert (tmp_path / 'history_legacy_unverified.csv').read_bytes() == original
    utils.save_csv(results, market_data={}, short_yield=dq.invalid('source', 'failed'), path=path)
    assert len(list(csv.DictReader(path.open()))) == 1
    summary = utils.calculate_summary(results)
    payload = utils.build_discord_payload(results, '', summary)
    assert dq.UNAVAILABLE in json.dumps(payload, ensure_ascii=False)
    assert 'Valid Indicators: 2/15' in summary


def test_zero_valid_has_no_market_conclusion():
    summary = utils.calculate_summary({})
    assert '无法形成市场结论' in summary
    assert 'Risk On' not in summary and 'Risk Off' not in summary


def test_missing_webhook_skips_network(monkeypatch):
    monkeypatch.delenv('DISCORD_WEBHOOK_URL', raising=False)
    monkeypatch.setattr(utils.requests, 'post', lambda *a, **kw: pytest.fail('unexpected send'))
    assert utils.send_discord({}, '', '') == 'skipped'


def test_discord_failures_do_not_expose_url(monkeypatch, capsys):
    secret = 'https://discord.com/api/webhooks/123/do-not-print-this'
    monkeypatch.setenv('DISCORD_WEBHOOK_URL', secret)
    monkeypatch.setattr(utils.requests, 'post', lambda *a, **kw: type('Response', (), {'status_code': 401})())
    assert utils.send_discord({}, '', '') == 'failed'
    assert secret not in capsys.readouterr().out


def test_discord_payload_fits_limits():
    results = {k: dq.invalid('source' * 30, 'reason' * 100) for k in INDICATORS}
    embed = utils.build_discord_payload(results, 'market', utils.calculate_summary(results))['embeds'][0]
    assert len(embed['fields']) <= 25
    assert all(len(f['value']) <= 1024 for f in embed['fields'])
    size = len(embed['title']) + len(embed['footer']['text']) + sum(len(f['name']) + len(f['value']) for f in embed['fields'])
    assert size <= 6000


def test_browser_http_preserves_matching_user_agent(monkeypatch):
    captured = {}
    class Response:
        status_code = 200
        content = b'{}'
        def raise_for_status(self):
            pass
    def get(url, **kwargs):
        captured.update(kwargs)
        return Response()
    monkeypatch.setattr(dq.browser_requests, 'get', get)
    dq.get_response('https://www.aaii.com/sentimentsurvey', browser=True)
    assert 'User-Agent' not in captured['headers']
    assert captured['impersonate'] == 'chrome'


def test_http_200_challenge_is_not_market_data(monkeypatch):
    class Response:
        status_code = 200
        content = b'<title>Pardon Our Interruption</title>'
        def raise_for_status(self):
            pass
    monkeypatch.setattr(dq.browser_requests, 'get', lambda *a, **kw: Response())
    with pytest.raises(dq.SourceUnavailable, match='bot-check'):
        dq.get_response('https://www.aaii.com/sentimentsurvey', browser=True)


def test_missing_equity_session_does_not_silently_change_ma(monkeypatch):
    frame = pd.DataFrame({'Close': [100, 101]}, index=pd.DatetimeIndex(['2026-09-14', '2026-09-16'], tz='America/New_York'))
    monkeypatch.setattr(df.yf, 'Ticker', lambda _: type('Ticker', (), {'history': lambda self, **kw: frame})())
    with pytest.raises(ValueError, match='missing trading sessions'):
        df.history('HYG')


def test_invalid_components_still_serialize_to_strict_json(tmp_path):
    record = valid('AAII', -1, bull=float('nan'), neutral=29, bear=36, release_date='2026-09-17')
    assert record['status'] == 'invalid'
    utils.save_snapshot({'AAII': record}, {}, 'no data', path=tmp_path / 'latest.json')
    data = json.loads((tmp_path / 'latest.json').read_text())
    assert data['indicators']['AAII']['value'] is None
    assert data['indicators']['AAII']['details']['bull'] is None
