"""Existing Bull/Bear rules, with invalid observations excluded at every output."""
import csv
import json
import os
from pathlib import Path
import shutil
import tempfile
from urllib.parse import urlparse

import requests

from config import INDICATORS, IMAGES
import data_fetchers as df
from data_quality import (UNAVAILABLE, error_reason, invalid, latest_session, number,
                          utc_now, validate_result)

ROOT = Path(__file__).resolve().parent
CSV_KEYS = {
    'BOND_10Y': '10Y_Yield', 'RSI': 'RSI', 'VIX': 'VIX', 'CNN': 'CNN',
    'PUT_CALL': 'Put_Call', 'DXY': 'DXY', 'BTC': 'BTC_Chg', 'HYG': 'HYG_Price',
    'RISK_RATIO': 'Risk_Ratio', 'IWM': 'IWM_Price', 'SOXX': 'SOXX_Price',
    'NAAIM': 'NAAIM', 'SKEW': 'SKEW', 'AAII': 'AAII_Diff',
    'ABOVE_200_DAYS': 'Above_200MA',
}


def extract_numeric_value(text):
    try:
        return str(number(text))
    except (ValueError, TypeError, OverflowError):
        return ''


def get_indicator_status(key, value_in):
    record = validate_result(key, value_in)
    if record['status'] == 'delayed':
        return '🕒 延迟参考（不参与统计）'
    if record['status'] != 'valid':
        return UNAVAILABLE
    cfg = INDICATORS.get(key)
    if not cfg:
        return UNAVAILABLE
    val = record['value']
    thresholds = cfg['thresholds']
    details = record['details']
    if thresholds == 'ma_trend':
        if details['trend'] == 'Above':
            return '🟢 多頭排列' if key != 'HYG' else '🟢 資金流入'
        return '🔴 轉弱/空頭' if key != 'HYG' else '🔴 資金流出'
    if thresholds == 'arrow_trend':
        return '🟢 Risk On' if details['trend'] == 'Up' else '🔴 Risk Off'
    g_limit, r_limit = thresholds
    if key == 'BTC':
        if val > g_limit:
            return '🟢 大漲 (Risk On)'
        if val < r_limit:
            return '🔴 大跌 (Risk Off)'
        return '⚪ 波動正常'
    if key == 'PUT_CALL':
        if val > g_limit:
            return '🟢 看空過度 (偏多)'
        if val < r_limit:
            return '🔴 看多過度 (偏空)'
        return '⚪ 中性'
    if key == 'VIX':
        if val > g_limit:
            return '🟢 市場恐慌 (偏多)'
        if val < r_limit:
            return '🔴 市場自滿 (偏空)'
        return '⚪ 中性'
    if cfg.get('inverse'):
        if val <= g_limit:
            return '🟢 偏多'
        if val >= r_limit:
            return '🔴 偏空'
    else:
        if val >= g_limit:
            return '🟢 偏多'
        if val <= r_limit:
            return '🔴 偏空'
    return '⚪ 中性'


def direction(key, record):
    status = get_indicator_status(key, record)
    return 'Bull' if '🟢' in status else 'Bear' if '🔴' in status else 'Neutral' if '⚪' in status else 'Excluded'


def summary_counts(results):
    counts = {'valid': 0, 'total': len(INDICATORS), 'bull': 0, 'neutral': 0, 'bear': 0, 'invalid': 0, 'delayed': 0}
    for key in INDICATORS:
        record = validate_result(key, results.get(key))
        if record['status'] == 'delayed':
            counts['delayed'] += 1
            continue
        verdict = direction(key, record)
        if verdict == 'Excluded':
            counts['invalid'] += 1
        else:
            counts['valid'] += 1
            counts[verdict.lower()] += 1
    return counts


def calculate_summary(results):
    counts = summary_counts(results)
    conclusion = '⚪ 市場分歧，建議觀望'
    if counts['valid'] == 0:
        conclusion = '⚠️ 无有效指标，无法形成市场结论'
    elif counts['bull'] > counts['bear']:
        conclusion = '🟢 市場偏向恐懼/機會 (Risk On)'
    elif counts['bear'] > counts['bull']:
        conclusion = '🔴 市場偏向貪婪/風險 (Risk Off)'
    return (f"Valid Indicators: {counts['valid']}/{counts['total']}\n"
            f"Bull: {counts['bull']} | Neutral: {counts['neutral']} | Bear: {counts['bear']}\n"
            f"{conclusion}\n仅统计当前有效指标；延迟参考 {counts['delayed']} 项，缺失 {counts['invalid']} 项。"
            '沿用原项目规则，未校准预测能力。')


def format_value(key, record):
    record = validate_result(key, record)
    if record.get('status') not in {'valid', 'delayed'}:
        return UNAVAILABLE
    val, info = record['value'], record.get('details', {})
    if key == 'AAII':
        return (f"AAII Bull {info['bull']:.1f}% | AAII Bear {info['bear']:.1f}% | "
                f"Bull-Bear Spread {val:+.1f}pp | 调查发布日期 {info['release_date']} | "
                f"调查周截至 {info.get('survey_week_ending') or '见原始 Reported Date'}")
    suffix = '%' if key in {'BOND_10Y', 'BOND_3M', 'BTC', 'ABOVE_200_DAYS'} else ''
    text = f'{val:.2f}{suffix}'
    if key in {'HYG', 'IWM', 'SOXX'}:
        text += f" ({info['trend']} MA20 {info['ma20']:.2f})"
    elif key == 'RISK_RATIO':
        text += ' (↗️)' if info['trend'] == 'Up' else ' (↘️)'
    elif key == 'NAAIM':
        if record['status'] == 'delayed':
            text += f" | 延迟 {info['delay_days']} 天，仅供参考"
        text += f" | 周度发布日期 {info.get('release_date') or '源未提供'}"
    return text


def build_discord_payload(results, market_text, summary):
    counts = summary_counts(results)
    trend = 'BULL' if counts['bull'] > counts['bear'] else 'BEAR' if counts['bear'] > counts['bull'] else 'NEUTRAL'
    fields = [
        {'name': '🔮 市場情緒總結', 'value': summary[:600], 'inline': False},
        {'name': '📊 美股大盤指數', 'value': (market_text or UNAVAILABLE)[:500], 'inline': False},
    ]
    for key, cfg in INDICATORS.items():
        record = validate_result(key, results.get(key))
        text = (f"{format_value(key, record)}\n"
                f"{get_indicator_status(key, record)} | {record['status']}\n"
                f"来源: {record.get('source', 'unknown')[:80]}\n"
                f"数据日期: {record.get('data_date') or '未知'}")
        if record['status'] != 'valid':
            text += f"\n原因: {record.get('reason', '')[:120]}"
        fields.append({'name': cfg['name'], 'value': text[:500], 'inline': False})
    return {'embeds': [{
        'title': f"📅 每日財經情緒日報 ({utc_now().date()}; 各项以数据日期为准)",
        'color': {'BULL': 0x2ecc71, 'BEAR': 0xe74c3c, 'NEUTRAL': 0x95a5a6}[trend],
        'fields': fields, 'image': {'url': IMAGES[trend]},
        'footer': {'text': '仅有效数据参与原项目多空规则'},
        'timestamp': utc_now().isoformat(),
    }]}


def send_discord(results, market_text, summary):
    url = os.environ.get('DISCORD_WEBHOOK_URL', '').strip()
    if not url:
        print('Discord: skipped (DISCORD_WEBHOOK_URL 未设置)')
        return 'skipped'
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in {'discord.com', 'discordapp.com', 'canary.discord.com', 'ptb.discord.com'} or not parsed.path.startswith('/api/webhooks/'):
        print('Discord: invalid webhook configuration (URL hidden)')
        return 'failed'
    try:
        response = requests.post(url, json=build_discord_payload(results, market_text, summary),
                                 timeout=(10, 20), allow_redirects=False)
        if response.status_code not in {200, 204}:
            print(f'Discord: HTTP {response.status_code} (URL hidden)')
            return 'failed'
        print('Discord: sent')
        return 'sent'
    except Exception as exc:
        print(f'Discord: {error_reason(exc)} (URL hidden)')
        return 'failed'


def atomic_text(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='', dir=path.parent, delete=False) as handle:
            temp = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()


def save_snapshot(results, market_data, summary, path=None):
    cleaned = {key: validate_result(key, results.get(key)) for key in INDICATORS}
    payload = {'schema_version': 3, 'run_at': utc_now().isoformat(),
               'market_session': latest_session().isoformat(),
               'counts': summary_counts(cleaned), 'summary': summary,
               'indicators': cleaned, 'market_data': market_data}
    atomic_text(path or ROOT / 'data/latest.json', json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def save_csv(results, market_data=None, short_yield=None, path=None):
    """Upsert the session row; retain source date per field, never invent one."""
    from io import StringIO
    path = Path(path or ROOT / 'data/history.csv')
    path.parent.mkdir(parents=True, exist_ok=True)
    records = {CSV_KEYS[key]: validate_result(key, results.get(key)) for key in INDICATORS}
    market_data = df.fetch_full_market_data() if market_data is None else market_data
    records.update({k: validate_result(k, v) for k, v in market_data.items()})
    short_yield = df.fetch_short_term_yield() if short_yield is None else short_yield
    records['3M_Yield'] = validate_result('BOND_3M', short_yield)
    aaii = records['AAII_Diff']
    for name, detail in [('AAII_Bull', 'bull'), ('AAII_Bear', 'bear'), ('AAII_Neutral', 'neutral')]:
        records[name] = {**aaii, 'value': aaii.get('details', {}).get(detail) if aaii['status'] == 'valid' else None}
    row = {'Date': latest_session().isoformat(), 'Run_At': utc_now().isoformat(), 'Schema_Version': '3'}
    for name, record in records.items():
        row[name] = record['value'] if record['status'] in {'valid', 'delayed'} else ''
        for field in ('source', 'source_url', 'data_date', 'status', 'reason'):
            row[f'{name}_{field}'] = record.get(field) or ''
    row['AAII_Release_Date'] = aaii.get('details', {}).get('release_date') or ''
    row['AAII_Survey_Week_Ending'] = aaii.get('details', {}).get('survey_week_ending') or ''
    row['NAAIM_Release_Date'] = records['NAAIM'].get('details', {}).get('release_date') or ''
    for key, val in summary_counts(results).items():
        row[f'Count_{key}'] = val
    existing = []
    if path.exists() and path.stat().st_size:
        with path.open(encoding='utf-8-sig', newline='') as handle:
            reader = csv.DictReader(handle)
            previous_fields = [field for field in row if field != 'Count_delayed']
            if reader.fieldnames == previous_fields:
                existing = list(reader)
                if any(None in r or any(v is None for v in r.values()) or r['Schema_Version'] != '2' for r in existing):
                    raise ValueError('corrupt or unknown schema-2 CSV; refusing migration')
                backup = path.with_name('history_schema2_backup.csv')
                if backup.exists() and backup.read_bytes() != path.read_bytes():
                    raise ValueError('schema-2 backup conflict; refusing to overwrite')
                if not backup.exists():
                    shutil.copy2(path, backup)
                for old in existing:
                    old.update({'Schema_Version': '3', 'Count_delayed': '0'})
                print('CSV schema 2 → 3: 原文件已备份；新增 delayed 参考状态及独立计数')
            elif reader.fieldnames != list(row):
                if 'Schema_Version' in (reader.fieldnames or []):
                    raise ValueError('unexpected validated CSV schema; refusing to overwrite')
                # The upstream file has known 0/-1 contamination and no provenance.
                backup = path.with_name('history_legacy_unverified.csv')
                if backup.exists() and backup.read_bytes() != path.read_bytes():
                    raise ValueError('legacy backup conflict; refusing to overwrite')
                if not backup.exists():
                    shutil.copy2(path, backup)
                print(f'旧历史已原样隔离: {backup.name} (unverified; 不参与统计)')
            else:
                existing = list(reader)
                if any(None in r or any(v is None for v in r.values()) for r in existing):
                    raise ValueError('corrupt CSV row; refusing to overwrite')
    existing = [r for r in existing if r['Date'] != row['Date']]
    existing.append(row)
    existing.sort(key=lambda r: r['Date'])
    buffer = StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=list(row), lineterminator='\n')
    writer.writeheader()
    writer.writerows(existing)
    atomic_text(path, buffer.getvalue())
    print(f"CSV: {path} | market session {row['Date']} | invalid values are blank")
    return row
