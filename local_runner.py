"""Small launchd entry point; use the existing collectors and delivery receipts."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from dotenv import load_dotenv
import requests

import schedule_guard as sg

ROOT = Path(__file__).resolve().parent


def save_status(path, value):
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as file:
        temp = Path(file.name)
        json.dump(value, file, ensure_ascii=False, indent=2)
        file.write('\n')
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp, path)


def can_notify():
    """A read-only check before claiming a slot; offline startup can safely retry."""
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    if not token or not os.environ.get('TELEGRAM_CHAT_ID', '').strip():
        return False
    try:
        response = requests.get(f'https://api.telegram.org/bot{token}/getMe',
                                timeout=(5, 10), allow_redirects=False)
        payload = response.json() if response.status_code == 200 else {}
        return (payload.get('ok') is True
                and str((payload.get('result') or {}).get('id')) == token.split(':')[0])
    except Exception:
        # A requests exception can contain the token-bearing URL.
        return False


def execute_report(slot, log):
    args = [sys.executable, str(ROOT / 'main.py')]
    if slot:
        args.extend(['--scheduled-slot', slot])
    return subprocess.run(args, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                          timeout=15 * 60, start_new_session=True).returncode


def run(*, once=False, now=None):
    os.umask(0o077)
    load_dotenv(ROOT / '.env', override=False)
    private = ROOT / 'data/private'
    logs = ROOT / 'logs'
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    logs.mkdir(parents=True, exist_ok=True, mode=0o700)
    now = now or datetime.now(timezone.utc)
    with (private / 'local-run.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        check = sg.decision(now=now)
        status = {'checked_at': now.isoformat(), 'slot': check['slot'],
                  'mode': 'acceptance' if once else 'scheduled', 'pid': os.getpid()}
        if not once and not check['send']:
            save_status(private / 'last_check.json',
                        {**status, 'status': 'skipped', 'reason': check['reason']})
            return 0
        if not can_notify():
            save_status(private / 'last_check.json', {**status, 'status': 'waiting_for_network'})
            print('Local runner: Telegram preflight unavailable; slot remains eligible for retry', flush=True)
            return 2
        slot = None if once else check['slot']
        if slot:
            sg.claim(slot, now=now)
        save_status(private / 'last_check.json', {**status, 'status': 'running'})
        logfile = logs / f"run-{now:%Y%m%dT%H%M%S}-{os.getpid()}.log"
        with logfile.open('a', buffering=1) as log, redirect_stdout(log), redirect_stderr(log):
            print(f"Local runner: {status['mode']} | started {now.isoformat()}")
            try:
                code = execute_report(slot, log)
            except Exception as exc:
                print(f'Local runner: {type(exc).__name__}; exception content withheld')
                code = 2
        receipt = sg.load_state()['slots'].get(slot, {}) if slot else {}
        result = {**status, 'finished_at': datetime.now(timezone.utc).isoformat(),
                  'exit_code': code, 'receipt_status': receipt.get('status'),
                  'log': str(logfile)}
        save_status(private / 'last_run.json', result)
        save_status(private / 'last_check.json',
                    {**status, 'status': 'completed' if code == 0 else 'failed',
                     'finished_at': result['finished_at']})
        print(f"Local runner: completed | exit={code} | receipt={receipt.get('status')} | log={logfile}", flush=True)
        return code


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-once', action='store_true', help='Explicit one-time acceptance report')
    args = parser.parse_args()
    raise SystemExit(run(once=args.run_once))
