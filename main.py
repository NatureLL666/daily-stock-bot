"""Daily entry point: collect, validate, report, save, then optionally notify."""
import data_fetchers as df
import utils
from dotenv import load_dotenv
from config import INDICATORS
from data_quality import error_reason, invalid, validate_result
from telegram_push import send_telegram


def fetch_all_indices():
    results = {}
    print('开始抓取 15 项指标；所有值保留来源、原始数据日期和有效性。', flush=True)
    for key, cfg in INDICATORS.items():
        print(f"[{key}] {cfg['name']} ...", flush=True)
        try:
            if cfg['type'] == 'price':
                value = df.fetch_yf_price(cfg['ticker'], cfg.get('correction', 1.0))
            elif cfg['type'] == 'trend':
                value = df.fetch_yf_trend(cfg['ticker'])
            else:
                value = cfg['func']()
            record = validate_result(key, value)
        except Exception as exc:
            record = invalid('fetcher failure', error_reason(exc))
        results[key] = record
        print(f"  当前值: {utils.format_value(key, record)}\n"
              f"  来源: {record.get('source')}\n"
              f"  数据日期: {record.get('data_date') or '未知'}\n"
              f"  状态: {record['status']} | {utils.direction(key, record)} | {utils.get_indicator_status(key, record)}",
              flush=True)
        if record['status'] != 'valid':
            print(f"  原因: {record.get('reason', 'unknown')}", flush=True)
    return results


def main():
    load_dotenv(utils.ROOT / '.env', override=False)
    results = fetch_all_indices()
    market_text = df.fetch_market_info()
    market_data = df.fetch_full_market_data()
    short_yield = df.fetch_short_term_yield()
    summary = utils.calculate_summary(results)
    print('\n' + market_text + '\n\n' + summary, flush=True)
    utils.save_csv(results, market_data, short_yield)
    utils.save_snapshot(results, {**market_data, 'BOND_3M': short_yield}, summary)
    deliveries = [utils.send_discord(results, market_text, summary),
                  send_telegram(results, market_text, summary)]
    # A broken network must be visible in Actions, not a green all-invalid run.
    return 2 if utils.summary_counts(results)['valid'] == 0 or 'failed' in deliveries else 0


if __name__ == '__main__':
    raise SystemExit(main())
