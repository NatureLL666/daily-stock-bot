from datetime import datetime, timedelta, timezone
from pathlib import Path
import csv
from io import StringIO
import json

import pytest

import data_quality as dq
import utils
from naaim_index import parse_naaim_table
from telegram_push import build_telegram_messages

NOW = datetime(2026, 9, 17, 14, 0, tzinfo=timezone.utc)
HTML = (Path(__file__).parent / 'fixtures/naaim.html').read_text()


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(dq, 'utc_now', lambda: NOW)
    monkeypatch.setattr(utils, 'utc_now', lambda: NOW)


def test_delayed_reference_is_visible_but_never_votes(tmp_path):
    record = parse_naaim_table(HTML, NOW)
    results = {'NAAIM': record}
    summary = utils.calculate_summary(results)
    assert 'Valid Indicators: 0/15' in summary
    assert 'Bull: 0 | Neutral: 0 | Bear: 0' in summary
    assert '延迟参考 1 项，缺失 14 项' in summary
    assert '无法形成市场结论' in summary
    assert 'Risk On' not in summary
    report = '\n'.join(build_telegram_messages(results, '', summary))
    assert '79.27 | 延迟 99 天，仅供参考' in report
    assert '数据日期: 2026-06-10' in report
    assert 'delayed | Excluded' in report
    assert '周度发布日期 源未提供' in report
    discord = json.dumps(utils.build_discord_payload(results, '', summary), ensure_ascii=False)
    assert '79.27 | 延迟 99 天' in discord
    row = utils.save_csv(results, {}, dq.invalid('source', 'missing'), path=tmp_path / 'history.csv')
    assert row['NAAIM'] == 79.27 and row['NAAIM_status'] == 'delayed'
    assert row['NAAIM_data_date'] == '2026-06-10'
    assert row['NAAIM_Release_Date'] == ''
    assert row['Count_delayed'] == 1 and row['Count_valid'] == 0
    utils.save_snapshot(results, {}, summary, path=tmp_path / 'latest.json')
    snapshot = json.loads((tmp_path / 'latest.json').read_text())
    assert snapshot['indicators']['NAAIM']['value'] == 79.27
    assert snapshot['indicators']['NAAIM']['status'] == 'delayed'


@pytest.mark.parametrize('value', [0, 'error -1', None, '', 'N/A', 'error 403', float('nan'), 201])
def test_invalid_reference_is_not_rescued_by_delayed_label(value):
    record = parse_naaim_table(HTML, NOW)
    record['value'] = value
    checked = dq.validate_result('NAAIM', record)
    assert checked['status'] == 'invalid' and checked['value'] is None
    assert utils.format_value('NAAIM', checked) == dq.UNAVAILABLE


def test_delayed_state_cannot_authorize_other_sources_or_indicators():
    record = parse_naaim_table(HTML, NOW)
    assert dq.validate_result('VIX', record)['status'] == 'invalid'
    record['source_url'] = 'https://unverified.example/'
    assert dq.validate_result('NAAIM', record)['status'] == 'invalid'


def test_reference_age_is_recomputed_and_eventually_expires():
    record = parse_naaim_table(HTML, NOW)
    updated = dq.validate_result('NAAIM', record, now=NOW + timedelta(days=1))
    assert updated['details']['delay_days'] == 100
    assert updated['data_date'] == '2026-06-10'
    expired = dq.validate_result('NAAIM', record, now=NOW + timedelta(days=12))
    assert expired['status'] == 'invalid' and expired['value'] is None
    record['data_date'] = '2026-09-18'
    assert dq.validate_result('NAAIM', record)['status'] == 'invalid'


def test_schema2_csv_migrates_without_losing_previous_rows(tmp_path):
    path = tmp_path / 'history.csv'
    row = utils.save_csv({}, {}, dq.invalid('source', 'missing'), path=path)
    row.pop('Count_delayed')
    row.update({'Date': '2026-09-15', 'Schema_Version': '2'})
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(row))
    writer.writeheader()
    writer.writerow(row)
    path.write_text(buffer.getvalue())
    original = path.read_bytes()
    utils.save_csv({'NAAIM': parse_naaim_table(HTML, NOW)}, {}, dq.invalid('source', 'missing'), path=path)
    assert path.with_name('history_schema2_backup.csv').read_bytes() == original
    rows = list(csv.DictReader(path.open()))
    assert len(rows) == 2
    assert rows[0]['Date'] == '2026-09-15' and rows[0]['Count_delayed'] == '0'
    assert rows[1]['NAAIM_status'] == 'delayed'
    assert all(row['Schema_Version'] == '3' for row in rows)
