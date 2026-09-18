"""Optional Telegram delivery, using environment credentials and explicit chat binding."""
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from config import INDICATORS
from data_quality import UNAVAILABLE, utc_now, validate_result
from utils import direction, format_value, get_indicator_status


def utf16_length(text):
    return len(text.encode('utf-16-le')) // 2


def build_telegram_messages(results, market_text, summary):
    """Plain text avoids Markdown escaping; split at complete indicator boundaries."""
    sent_at = utc_now().astimezone(ZoneInfo('Asia/Shanghai'))
    heading = f"📊 美股情绪日报 · {sent_at:%Y-%m-%d %H:%M} 北京时间\n各项以数据日期为准"
    slot = os.environ.get('REPORT_SCHEDULED_FOR')
    if slot:
        planned = datetime.fromisoformat(slot).astimezone(ZoneInfo('Asia/Shanghai'))
        heading += f"\n计划时段: {planned:%Y-%m-%d %H:%M} 北京时间"
    blocks = [heading,
              summary[:700], (market_text or UNAVAILABLE)[:600]]
    for key, cfg in INDICATORS.items():
        record = validate_result(key, results.get(key))
        block = (f"{cfg['name']}\n{format_value(key, record)}\n"
                 f"{record['status']} | {direction(key, record)} | {get_indicator_status(key, record)}\n"
                 f"来源: {record.get('source', 'unknown')[:120]}\n"
                 f"数据日期: {record.get('data_date') or '未知'}")
        if record['status'] != 'valid':
            block += f"\n原因: {record.get('reason', '')[:180]}"
        blocks.append(block)
    messages, current = [], ''
    for block in blocks:
        if not block:
            continue
        if utf16_length(block) > 3500:
            raise ValueError('Telegram report block too long')
        candidate = current + '\n\n' + block if current else block
        if utf16_length(candidate) > 3500:
            messages.append(current)
            current = block
        else:
            current = candidate
    if current:
        messages.append(current)
    return [f'({index}/{len(messages)})\n{text}' for index, text in enumerate(messages, 1)]


def send_telegram(results, market_text, summary):
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
    if not token or not chat_id:
        print('Telegram: skipped (需要 TELEGRAM_BOT_TOKEN 和已绑定的 TELEGRAM_CHAT_ID)')
        return 'skipped'
    if not re.fullmatch(r'\d{5,}:[A-Za-z0-9_-]{30,}', token) or not re.fullmatch(r'-?[1-9]\d*', chat_id):
        print('Telegram: invalid configuration (credentials hidden)')
        return 'failed'
    sent = 0
    try:
        messages = build_telegram_messages(results, market_text, summary)
        for text in messages:
            response = requests.post(
                f'https://api.telegram.org/bot{token}/sendMessage',
                json={'chat_id': int(chat_id), 'text': text,
                      'link_preview_options': {'is_disabled': True}},
                timeout=(10, 20), allow_redirects=False)
            if response.status_code != 200:
                print(f'Telegram: HTTP {response.status_code}; confirmed parts {sent}/{len(messages)}')
                return 'failed'
            payload = response.json()
            result = payload.get('result') or {}
            if (payload.get('ok') is not True or not isinstance(result.get('message_id'), int)
                    or result.get('chat', {}).get('id') != int(chat_id)):
                print(f'Telegram: delivery not confirmed; confirmed parts {sent}/{len(messages)}')
                return 'failed'
            sent += 1
        print(f'Telegram: sent ({sent} parts; API confirmed destination)')
        return 'sent'
    except Exception as exc:
        # Requests exceptions contain the token-bearing URL. Never log their text.
        # No automatic retries: a timeout can occur after Telegram accepted a send.
        print(f'Telegram: {type(exc).__name__}; confirmed parts {sent}; no automatic retry')
        return 'failed'
