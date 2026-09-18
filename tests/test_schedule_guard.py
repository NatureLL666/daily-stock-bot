from datetime import datetime, timezone
from pathlib import Path
import json

import pytest

import schedule_guard as sg


def at(iso):
    return datetime.fromisoformat(iso).astimezone(timezone.utc)


@pytest.mark.parametrize('now,slot', [
    ('2026-09-17T23:00:00+00:00', '2026-09-18T07:00:00+08:00'),
    ('2026-09-18T00:06:00+00:00', '2026-09-18T07:00:00+08:00'),
    ('2026-09-18T13:00:00+00:00', '2026-09-18T21:00:00+08:00'),
    ('2026-09-18T14:15:00+00:00', '2026-09-18T21:00:00+08:00'),
])
def test_exact_slots_and_late_scheduler_catch_up(tmp_path, now, slot):
    result = sg.decision(now=at(now), path=tmp_path / 'state.json')
    assert result['send'] is True
    assert result['slot'] == slot


@pytest.mark.parametrize('now', ['2026-09-18T06:59:00+08:00', '2026-09-18T20:59:00+08:00',
                                '2026-09-18T11:00:00+08:00'])
def test_never_send_early_or_an_old_slot(tmp_path, now):
    assert sg.decision(now=at(now), path=tmp_path / 'state.json')['send'] is False


def test_successful_receipt_suppresses_later_backup_ticks(tmp_path):
    path = tmp_path / 'state.json'
    now = at('2026-09-18T07:05:00+08:00')
    slot = sg.decision(now=now, path=path)['slot']
    sg.claim(slot, path=path, now=now)
    sg.finish(slot, 'sent', path=path, now=now)
    assert sg.decision(now=at('2026-09-18T08:55:00+08:00'), path=path)['send'] is False
    assert sg.decision(now=at('2026-09-18T21:00:00+08:00'), path=path)['send'] is True
    assert sg.decision(now=at('2026-09-19T07:00:00+08:00'), path=path)['send'] is True


@pytest.mark.parametrize('outcome', ['sending', 'uncertain'])
def test_an_ambiguous_send_is_never_retried_blindly(tmp_path, outcome):
    path = tmp_path / 'state.json'
    now = at('2026-09-18T07:05:00+08:00')
    slot = sg.decision(now=now, path=path)['slot']
    sg.claim(slot, path=path, now=now)
    if outcome == 'uncertain':
        sg.finish(slot, 'failed', path=path, now=now)
    assert sg.decision(now=at('2026-09-18T07:15:00+08:00'), path=path)['send'] is False


def test_skipped_notification_is_not_marked_sent(tmp_path):
    path = tmp_path / 'state.json'
    now = at('2026-09-18T07:05:00+08:00')
    slot = sg.decision(now=now, path=path)['slot']
    sg.claim(slot, path=path, now=now)
    sg.finish(slot, 'skipped', path=path, now=now)
    assert sg.decision(now=at('2026-09-18T07:15:00+08:00'), path=path)['send'] is True


def test_corrupt_state_and_stale_claim_fail_closed(tmp_path):
    path = tmp_path / 'state.json'
    path.write_text('{bad json')
    with pytest.raises(ValueError):
        sg.decision(now=at('2026-09-18T07:00:00+08:00'), path=path)
    path.unlink()
    with pytest.raises(ValueError):
        sg.claim('2026-09-17T07:00:00+08:00', path=path, now=at('2026-09-18T07:00:00+08:00'))


def test_cannot_overwrite_a_confirmed_slot(tmp_path):
    path = tmp_path / 'state.json'
    now = at('2026-09-18T07:00:00+08:00')
    slot = sg.decision(now=now, path=path)['slot']
    sg.claim(slot, path=path, now=now)
    sg.finish(slot, 'sent', path=path, now=now)
    with pytest.raises(ValueError):
        sg.claim(slot, path=path, now=now)
    state = json.loads(path.read_text())
    assert state['slots'][slot]['status'] == 'sent'


def test_claim_writes_no_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'do-not-store-bot-token')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', 'do-not-store-chat-id')
    path = tmp_path / 'state.json'
    now = at('2026-09-18T07:00:00+08:00')
    sg.claim(sg.decision(now=now, path=path)['slot'], path=path, now=now)
    assert 'do-not-store' not in path.read_text()


def test_another_workflow_run_cannot_finish_the_claim(tmp_path, monkeypatch):
    path = tmp_path / 'state.json'
    now = at('2026-09-18T07:00:00+08:00')
    monkeypatch.setenv('GITHUB_RUN_ID', 'first-run')
    slot = sg.decision(now=now, path=path)['slot']
    sg.claim(slot, path=path, now=now)
    monkeypatch.setenv('GITHUB_RUN_ID', 'other-run')
    with pytest.raises(ValueError):
        sg.finish(slot, 'sent', path=path, now=now)


@pytest.mark.parametrize('delivery,status,code', [('sent', 'sent', 0), ('failed', 'uncertain', 2),
                                               ('skipped', 'not_sent', 2)])
def test_main_records_the_actual_telegram_outcome(tmp_path, monkeypatch, delivery, status, code):
    import main
    import data_quality as dq
    import utils
    now = at('2026-09-18T07:05:00+08:00')
    state_path = tmp_path / 'data/delivery_state.json'
    monkeypatch.setattr(sg, 'STATE_PATH', state_path)
    monkeypatch.setattr(dq, 'utc_now', lambda: now)
    monkeypatch.setattr(utils, 'utc_now', lambda: now)
    monkeypatch.setattr(utils, 'ROOT', tmp_path)
    monkeypatch.setattr(main, 'load_dotenv', lambda *a, **kw: None)
    monkeypatch.setenv('REPORT_SCHEDULED_FOR', '')
    slot = sg.decision(now=now)['slot']
    sg.claim(slot, now=now)
    record = dq.observation('VIX', 20, 'CBOE', '2026-09-17', source_url='https://cdn.cboe.com')
    monkeypatch.setattr(main, 'fetch_all_indices', lambda: {'VIX': record})
    monkeypatch.setattr(main.df, 'fetch_market_info', lambda: 'market')
    monkeypatch.setattr(main.df, 'fetch_full_market_data', lambda: {})
    monkeypatch.setattr(main.df, 'fetch_short_term_yield', lambda: dq.invalid('source', 'missing'))
    monkeypatch.setattr(utils, 'send_discord', lambda *a: 'skipped')
    monkeypatch.setattr(main, 'send_telegram', lambda *a: delivery)
    assert main.main(slot) == code
    assert sg.load_state()['slots'][slot]['status'] == status
    assert (tmp_path / 'data/latest.json').exists()
