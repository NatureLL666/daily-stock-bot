"""Beijing report slots and durable receipts; standard library only for the CI gate."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo

BEIJING = ZoneInfo('Asia/Shanghai')
STATE_PATH = Path(__file__).resolve().parent / 'data/delivery_state.json'
STATUSES = {'sending', 'sent', 'uncertain', 'not_sent'}


def load_state(path=None):
    path = Path(path or STATE_PATH)
    if not path.exists():
        return {'schema_version': 1, 'slots': {}}
    state = json.loads(path.read_text())
    if (not isinstance(state, dict) or state.get('schema_version') != 1
            or not isinstance(state.get('slots'), dict)
            or any(not isinstance(r, dict) or r.get('status') not in STATUSES
                   for r in state['slots'].values())):
        raise ValueError('invalid delivery state; refusing duplicate notification')
    return state


def decision(*, now=None, path=None):
    local = (now or datetime.now(timezone.utc)).astimezone(BEIJING)
    candidates = [(local - timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)
                  for days in (0, 1) for hour in (7, 21)]
    due = max(t for t in candidates if t <= local)
    slot = due.isoformat()
    state = load_state(path)
    if local - due >= timedelta(hours=3):
        return {'send': False, 'slot': slot, 'reason': 'outside the report catch-up window'}
    prior = state['slots'].get(slot, {}).get('status')
    if prior in {'sent', 'sending', 'uncertain'}:
        return {'send': False, 'slot': slot, 'reason': f'existing receipt: {prior}'}
    return {'send': True, 'slot': slot, 'reason': 'due report has no delivery attempt'}


def write_state(state, path=None):
    path = Path(path or STATE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep a month of twice-daily public delivery metadata, without chat IDs/tokens.
    state['slots'] = dict(sorted(state['slots'].items())[-64:])
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as file:
            temp = Path(file.name)
            json.dump(state, file, ensure_ascii=False, indent=2)
            file.write('\n')
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp, path)
    finally:
        if temp and temp.exists():
            temp.unlink()


def claim(slot, *, now=None, path=None):
    check = decision(now=now, path=path)
    if not check['send'] or check['slot'] != slot:
        raise ValueError('slot is already attempted or no longer due')
    state = load_state(path)
    state['slots'][slot] = {'status': 'sending',
                            'attempted_at': (now or datetime.now(timezone.utc)).isoformat(),
                            'github_run_id': os.environ.get('GITHUB_RUN_ID')}
    write_state(state, path)


def verify_claim(slot, *, path=None):
    record = load_state(path)['slots'].get(slot, {})
    if record.get('status') != 'sending' or record.get('github_run_id') != os.environ.get('GITHUB_RUN_ID'):
        raise ValueError('this run does not own the persisted delivery claim')


def finish(slot, outcome, *, now=None, path=None):
    verify_claim(slot, path=path)
    state = load_state(path)
    state['slots'][slot].update({
        'status': {'sent': 'sent', 'skipped': 'not_sent'}.get(outcome, 'uncertain'),
        'finished_at': (now or datetime.now(timezone.utc)).isoformat(),
    })
    write_state(state, path)


def cli():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    parser.add_argument('--claim')
    args = parser.parse_args()
    if args.claim:
        claim(args.claim)
        print(f'Schedule: claimed {args.claim}; persist this file before sending')
        return
    check = decision()
    print(f"Schedule: {check['slot']} | send={check['send']} | {check['reason']}")
    if args.output:
        with args.output.open('a') as file:
            file.write(f"send={str(check['send']).lower()}\nslot={check['slot']}\n")


if __name__ == '__main__':
    cli()
