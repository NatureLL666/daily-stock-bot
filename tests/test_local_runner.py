from datetime import datetime, timezone
import fcntl
import json

import pytest

import local_runner as runner
import schedule_guard as sg


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    monkeypatch.setattr(sg, 'STATE_PATH', tmp_path / 'data/delivery_state.json')
    monkeypatch.setattr(runner, 'load_dotenv', lambda *a, **kw: False)
    monkeypatch.setattr(runner, 'can_notify', lambda: True)
    monkeypatch.delenv('GITHUB_RUN_ID', raising=False)
    return tmp_path


def due():
    return datetime(2026, 9, 18, 13, 0, tzinfo=timezone.utc)


def test_local_due_run_owns_claim_and_deduplicates(runtime, monkeypatch):
    calls = []

    def report(slot):
        sg.verify_claim(slot)
        calls.append(slot)
        sg.finish(slot, 'sent', now=due())
        return 0

    monkeypatch.setattr(runner, 'execute_report', lambda slot, log: report(slot))
    assert runner.run(now=due()) == 0
    assert json.loads((runtime / 'data/private/last_check.json').read_text())['status'] == 'completed'
    assert runner.run(now=due()) == 0
    assert calls == ['2026-09-18T21:00:00+08:00']
    status = json.loads((runtime / 'data/private/last_run.json').read_text())
    assert status['receipt_status'] == 'sent'


def test_network_unavailable_does_not_consume_the_slot(runtime, monkeypatch):
    monkeypatch.setattr(runner, 'can_notify', lambda: False)
    assert runner.run(now=due()) == 2
    assert sg.load_state()['slots'] == {}
    assert sg.decision(now=due())['send'] is True
    assert json.loads((runtime / 'data/private/last_check.json').read_text())['status'] == 'waiting_for_network'


def test_no_early_or_old_delivery_and_no_network_work(runtime, monkeypatch):
    monkeypatch.setattr(runner, 'can_notify', lambda: pytest.fail('network check outside report window'))
    assert runner.run(now=datetime(2026, 9, 18, 2, 30, tzinfo=timezone.utc)) == 0
    assert sg.load_state()['slots'] == {}


def test_overlapping_process_cannot_send(runtime, monkeypatch):
    private = runtime / 'data/private'
    private.mkdir(parents=True)
    with (private / 'local-run.lock').open('a') as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        monkeypatch.setattr(runner, 'can_notify', lambda: pytest.fail('concurrent notification'))
        assert runner.run(now=due()) == 0
    assert sg.load_state()['slots'] == {}


def test_crash_remains_visible_without_unsafe_resend(runtime, monkeypatch):
    def report(slot):
        raise RuntimeError('private-exception-content')

    monkeypatch.setattr(runner, 'execute_report', lambda slot, log: report(slot))
    assert runner.run(now=due()) == 2
    assert not sg.decision(now=due())['send']
    assert 'private-exception-content' not in next((runtime / 'logs').glob('run-*.log')).read_text()
    assert json.loads((runtime / 'data/private/last_run.json').read_text())['exit_code'] == 2


def test_acceptance_run_does_not_modify_regular_delivery_slots(runtime, monkeypatch):
    calls = []
    monkeypatch.setattr(runner, 'execute_report', lambda slot, log: calls.append(slot) or 0)
    assert runner.run(once=True, now=due()) == 0
    assert calls == [None]
    assert sg.load_state()['slots'] == {}
