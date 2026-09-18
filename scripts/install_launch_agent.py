"""Install the authorized personal macOS runtime without Documents dependencies."""
import argparse
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

from dotenv import set_key

SOURCE = Path(__file__).resolve().parents[1]
LABEL = 'local.daily-stock-bot'
RUNTIME = Path.home() / 'Library/Application Support/DailyStockBot'
PLIST = Path.home() / f'Library/LaunchAgents/{LABEL}.plist'


def configuration(runtime):
    return {
        'Label': LABEL,
        'ProgramArguments': [str(runtime / '.venv/bin/python'), str(runtime / 'local_runner.py')],
        'WorkingDirectory': str(runtime),
        'RunAtLoad': True,
        'StartCalendarInterval': [{'Hour': 7, 'Minute': 0}, {'Hour': 21, 'Minute': 0}],
        'StartInterval': 300,
        'ProcessType': 'Background',
        'ThrottleInterval': 120,
        'EnvironmentVariables': {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin',
                                 'TZ': 'Asia/Shanghai', 'PYTHONUNBUFFERED': '1'},
        'StandardOutPath': str(runtime / 'logs/launchd.log'),
        'StandardErrorPath': str(runtime / 'logs/launchd-error.log'),
    }


def install(*, start=True):
    if sys.platform != 'darwin' or sys.version_info[:2] != (3, 11):
        raise SystemExit('Run this installer using the project Python 3.11 on macOS.')
    if not (SOURCE / '.env').is_file():
        raise SystemExit('Local .env is missing; no installation performed.')
    os.umask(0o077)
    RUNTIME.mkdir(parents=True, exist_ok=True, mode=0o700)
    RUNTIME.chmod(0o700)
    (RUNTIME / 'logs').mkdir(exist_ok=True, mode=0o700)
    (RUNTIME / 'data/private').mkdir(parents=True, exist_ok=True, mode=0o700)
    # python-build-standalone is relocatable; create a fresh venv after copying it.
    base = Path(sys._base_executable).resolve().parent.parent
    if base == SOURCE or not (base / 'lib/python3.11').is_dir():
        raise SystemExit('Unexpected Python layout; refusing to guess a runtime.')
    python_root = RUNTIME / 'python'
    if not python_root.exists():
        shutil.copytree(base, python_root, symlinks=True)
    python = python_root / 'bin/python3.11'
    subprocess.run([str(python), '-m', 'venv', str(RUNTIME / '.venv')], check=True)
    for source in SOURCE.glob('*.py'):
        shutil.copy2(source, RUNTIME / source.name)
    shutil.copy2(SOURCE / 'requirements.txt', RUNTIME / 'requirements.txt')
    for source in (SOURCE / 'data').iterdir():
        if source.is_file() and source.suffix in {'.csv', '.json'}:
            target = RUNTIME / 'data' / source.name
            if not target.exists():
                shutil.copy2(source, target)
    if not (RUNTIME / '.env').exists():
        shutil.copy2(SOURCE / '.env', RUNTIME / '.env')
    # launchd does not inherit the terminal's network proxy environment.
    for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY',
                'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'):
        if os.environ.get(key):
            set_key(RUNTIME / '.env', key, os.environ[key], quote_mode='always')
    (RUNTIME / '.env').chmod(0o600)
    venv = RUNTIME / '.venv/bin/python'
    subprocess.run([str(venv), '-m', 'pip', 'install', '--quiet',
                    '--cache-dir', str(RUNTIME / '.cache/pip'),
                    '-r', str(RUNTIME / 'requirements.txt')], check=True)
    subprocess.run([str(venv), '-m', 'pip', 'check'], check=True)
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    if PLIST.exists():
        with PLIST.open('rb') as file:
            old = plistlib.load(file)
        if old.get('Label') != LABEL:
            raise SystemExit('An unrelated launch agent occupies the destination.')
        subprocess.run(['/bin/launchctl', 'bootout', f'gui/{os.getuid()}/{LABEL}'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with PLIST.open('wb') as file:
        plistlib.dump(configuration(RUNTIME), file)
    PLIST.chmod(0o600)
    subprocess.run(['/usr/bin/plutil', '-lint', str(PLIST)], check=True)
    if start:
        subprocess.run(['/bin/launchctl', 'enable', f'gui/{os.getuid()}/{LABEL}'], check=True)
        subprocess.run(['/bin/launchctl', 'bootstrap', f'gui/{os.getuid()}', str(PLIST)], check=True)
    print(f'Runtime: {RUNTIME}\nLaunchAgent: {PLIST}\nLoaded: {start}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare-only', action='store_true')
    install(start=not parser.parse_args().prepare_only)
