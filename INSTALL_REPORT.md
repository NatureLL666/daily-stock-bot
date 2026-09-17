# 安装、修复与运行报告

核验时点：2026-09-17T14:21:47.840091+00:00。工作目录：当前 daily-stock-bot。

① 项目是否成功运行

已 clone、通读全部源文件、创建 Python 3.11.16 虚拟环境并安装依赖。多次执行完整入口，最新一次退出码 0，Telegram API 确认向已绑定私人会话发送 1 条完整报告。保留全部 15 指标及原多空规则；当前 14 项有效，AAII 已通过官方页面的备用传输恢复，NAAIM 按用户要求使用免费公开延迟数据，显示真实值及日期，以 delayed 独立计数。

② 哪些数据源原本失效

Google Finance 的 10Y/SKEW 旧 CSS 选择器已失效；NAAIM 改为延迟公开表及订阅；StockQ AAII 的数据顺序、时间和内容不能用于最新调查。CBOE Put/Call 原返回值缺少回溯日期；Fear & Greed 原第三方页面没有可靠日期。Barchart 直接请求被 JS challenge 拦截。另已复现错误字符串被抽取数字、零值被判 Bull。详见 [来源审计](docs/source-audit.md)。

③ 修复了哪些文件

保留原模块调用架构。修改文件：`main.py`、`config.py`、`utils.py`、`data_fetchers.py`、`put_call_ratio.py`、`aaii_index.py`、`naaim_index.py`、`skew_index.py`、`treasury_yield.py`、`fear_greed_index.py`、`vix.py`、`above_200_days_average.py`、`requirements.txt`、`README.md`、`.github/workflows/daily_run.yml`。新增 `data_quality.py`、`telegram_push.py`、`requirements-dev.txt`、`.env.example`、`.gitignore`、`tests/` 与来源审计文档。原 CSV 原样隔离到 history_legacy_unverified.csv，SHA-256 校验与 upstream HEAD 完全相同。

Telegram 使用环境变量 `TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`。本机凭据在忽略版控的 `.env`，权限 0600；会话由本次一次性 `/start` 标记确认，不复用旧机器人或猜测历史收件人。所有候选项目文件已检查，无真实 token/API key。推送响应/异常不打印凭据或 chat ID，超时不自动重试；先保存 CSV/JSON 后投递。

④ 每个指标的数据来源和 ⑥ 本地运行结果

| 指标 | 当前值 | 来源 | 数据日期 | 状态 | 原规则判读 |
|---|---:|---|---|---|---|
| BOND_10Y | 5.00% | [FRED / Federal Reserve DGS10](https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10) | 2026-09-15 | valid | Bear |
| DXY | 100.31 | [Yahoo Finance (DX-Y.NYB)](https://finance.yahoo.com/quote/DX-Y.NYB/history/) | 2026-09-16 | valid | Bull |
| HYG | 78.42 | [Yahoo Finance (HYG, adjusted close)](https://finance.yahoo.com/quote/HYG/history/) | 2026-09-16 | valid | Bear |
| BTC | 0.71% | [Yahoo Finance (BTC-USD)](https://finance.yahoo.com/quote/BTC-USD/history/) | 2026-09-16 | valid | Neutral |
| IWM | 283.92 | [Yahoo Finance (IWM, adjusted close)](https://finance.yahoo.com/quote/IWM/history/) | 2026-09-16 | valid | Bear |
| SOXX | 502.06 | [Yahoo Finance (SOXX, adjusted close)](https://finance.yahoo.com/quote/SOXX/history/) | 2026-09-16 | valid | Bear |
| RISK_RATIO | 1.32 | [Yahoo Finance (XLY/XLP)](https://finance.yahoo.com/quote/XLY/history/) | 2026-09-16 | valid | Bear |
| RSI | 41.09 | [Yahoo Finance (^GSPC), original RSI(14)](https://finance.yahoo.com/quote/%5EGSPC/history/) | 2026-09-16 | valid | Neutral |
| VIX | 17.71 | [CBOE daily CSV](https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv) | 2026-09-16 | valid | Neutral |
| CNN | 29.31 | [CNN Fear & Greed JSON](https://production.dataviz.cnn.io/index/fearandgreed/graphdata) | 2026-09-17 | valid | Bull |
| ABOVE_200_DAYS | 50.09% | [TradingView INDEX:S5TH](https://www.tradingview.com/symbols/INDEX-S5TH/) | 2026-09-16 | valid | Neutral |
| NAAIM | 79.27（延迟 99 天） | [NAAIM official weekly table (public delayed access)](https://index.naaim.org/embeddable/table) | 2026-06-10 | delayed | Excluded |
| SKEW | 145.95 | [CBOE daily CSV](https://cdn.cboe.com/api/global/us_indices/daily_prices/SKEW_History.csv) | 2026-09-16 | valid | Bear |
| AAII | −24.5pp | [AAII 官方调查页，经 Firecrawl 原始 HTML 传输](https://www.aaii.com/sentimentsurvey) | 2026-09-17 发布；9/16 调查周截止 | valid | Bull |
| PUT_CALL | 0.98 | [CBOE TOTAL PUT/CALL RATIO](https://www.cboe.com/markets/us/options/market-statistics/daily?dt=2026-09-16) | 2026-09-16 | valid | Neutral |

```text
Valid Indicators: 14/15
Bull: 3 | Neutral: 5 | Bear: 6
Exit code: 0
Discord: skipped (DISCORD_WEBHOOK_URL 未设置)
Telegram: sent (1 parts; API confirmed destination)
```

原算法输出 Risk Off，仅由 14 项有效数据决定，不是新的评分模型或收益预测。FRED 5.00% 的观察日为 9/15，不能称为 9/17 实时报价。AAII Bull 28.8%、Neutral 17.9%、Bear 53.3%，保留 9/17 原始发布日期；CSV 与 JSON 的日期、有效值及计数一致，NAAIM 保存真实值且 status=delayed，仅作为历史参考；1 项延迟参考、0 项缺失。完整终端记录：[local-run-delayed-naaim.log](evidence/local-run-delayed-naaim.log)，结构化快照：[latest.json](data/latest.json)，CSV：[history.csv](data/history.csv)。

⑤ 当前风险

- NAAIM 公开最新行是 2026-06-10 = 79.27。按用户选择继续使用，以 delayed 展示值、原日期及 99 天延迟，排除当前多空统计；仅此官方表允许延迟参考，超过 110 日或数值异常仍 invalid。发布日期未披露，保持空值。
- AAII 官方 XLS/页面直连仍被反爬拦截。本次复用现有 Firecrawl 账户，通过实时 `maxAge=0` 请求取得同一官方页面的 rawHtml，独立请求与完整入口运行均验证成功。只解析原始 HTML，不用 AI 生成或提取的数值、不读本地旧缓存。备用通道依赖服务额度；没有 key 或抓取失败时仍会 invalid。
- CNN、AAII、TradingView、CBOE 页面内 JSON 不保证接口/页面永久不变；Yahoo 也可能限流。异常时显示 invalid，不填 0/-1。
- 旧历史已含错误数据、缺少逐指标时间证据，只保留原始档案，不宣称已修复全部历史行情。

⑦ GitHub Actions 是否可以直接部署

已按用户选择改为每天北京时间 07:00 / 21:00（含周末），对应 UTC 23:00 / 13:00；目标仓库为 NatureLL666/daily-stock-bot。GitHub 定时可能排队延迟，实际消息在采集完成后发送。云端部署结果另记于下方。checkout 已更新到官方稳定 v7.0.1，setup-python 到 v7.0.0；Ubuntu/Python 3.11；增加权限、串行、超时、回归测试、数据质量摘要及安全提交顺序。

验证：100 项回归测试通过，覆盖 Telegram 长消息分段、无配置跳过、错误目标/HTTP 拒绝、超时不重试与脱敏、推送失败保留本地数据，以及 AAII 官方页面备用来源、日期、过期/空内容拒绝等。pip check、Python 语法、YAML 和所有 shell 片段通过；Ubuntu x86_64/Python 3.11 的 37 项 wheel 依赖解析成功，本次未引入新依赖。Telegram 实际投递已确认。本机无 Linux VM/Docker；云端 Actions 实跑结果待部署验证。Discord Webhook 未测试。源站可能同样限制 GitHub 的出口 IP。

⑧ 下一步

本地已可直接运行 `.venv/bin/python main.py`，并自动发送 Telegram。用户已选择 GitHub Actions 每天北京时间 07:00 / 21:00，且已完成 GitHub CLI 登录。云端凭据仅使用加密 Repository secrets `TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`、`FIRECRAWL_API_KEY`，不会上传本机 `.env`。

NAAIM 当前无需订阅。公开延迟数据作为历史参考保留，如将来需要最新一期，可再接入合法周度导出。没有建立本机定时服务。

此阶段已完成可执行安装、错误数据隔离与来源替换；当前为 14 项有效数据 + 1 项延迟参考，不宣称全部是当期数据。Trend/Sentiment/Contrarian Score 留在第二阶段。
