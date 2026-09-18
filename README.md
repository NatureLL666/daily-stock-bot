# 📈 Daily Stock Index Bot（美股情绪机器人）

Python 3.11 每日采集 → 原项目多空判读 → CSV / JSON 历史 → 可选 Telegram / Discord 推送。保留 GitHub Actions 定时运行及全部 15 个指标，不包含第二阶段评分模型。

2026-09-17 最新修复已恢复 AAII 官方页抓取。按用户选择，NAAIM 使用官方公开的延迟数据：展示真实数值、原始日期及延迟天数，以 `delayed` 单独统计，不进入当前 Bull/Neutral/Bear。抓取失败仍是 `invalid`。最新实跑及 Telegram 投递结果见 [安装检查报告](INSTALL_REPORT.md)，逐项来源见 [来源审计](docs/source-audit.md)。

2026-09-18 用户选择改为本机定时推送：每天北京时间 **07:00、21:00**，使用 macOS `launchd` 和独立运行目录；GitHub 保留手动执行，停止云端自动推送。安装和真实系统定时验收见 [本地部署记录](docs/local-deployment.md)。

## 本地运行

本机已经安装 Python 3.11.16 并创建 `.venv`，在项目目录执行：

```bash
source .venv/bin/activate
python main.py
```

在另一台已有 Python 3.11 的机器上：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

检查：

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m pip check
```

生产采集不依赖 Selenium、Chrome 或 ChromeDriver。Yahoo 使用 yfinance；官方 CSV/JSON 与公开页面通过 requests / curl_cffi 获取。curl_cffi 保留其匹配的浏览器请求头；这不能保证网站永不限流或反爬。

## 指标及来源

| 指标 | 当前采集来源 | 数据口径 |
|---|---|---|
| 10Y Treasury | FRED DGS10；失败时 Yahoo `^TNX` | 百分数，保留观察日；不按数值猜测除以 10 |
| DXY | Yahoo `DX-Y.NYB` | 最近完整交易日 |
| HYG、IWM、SOXX | Yahoo 对应 ETF | 收盘 / MA20，沿用原公式 |
| BTC | Yahoo `BTC-USD` | 两个已完成 UTC 日的涨跌幅 |
| XLY/XLP Risk Ratio | Yahoo XLY、XLP | 同一对完整交易日的原始收盘价比值 |
| RSI | Yahoo `^GSPC` | 原项目 RSI(14) 公式 |
| VIX、SKEW | CBOE 官方日线 CSV | 原始 DATE、VIX CLOSE / SKEW |
| Fear & Greed | CNN JSON | 自带 timestamp，可能为盘中更新 |
| Above 200MA | TradingView `INDEX:S5TH` 公开日线 JSON | S&P 500 股票高于 200 日线的百分比 |
| Put/Call | CBOE 官网页面内结构化 JSON | **TOTAL PUT/CALL RATIO**，校验 selectedDate |
| AAII | AAII 官方 XLS + 最新调查页；可选 Firecrawl 备用传输 | Bull%、Bear%、Spread、调查周及发布日期 |
| NAAIM | NAAIM 官方周度表 / 可选授权导出 | 公开表以 delayed 展示，保留观察日，不参与当前多空统计 |

每个指标返回 `value / source / source_url / data_date / status / reason / fetched_at / details`。AAII 的 `data_date` 是发布日期，调查周截止日另存 `details.survey_week_ending`；NAAIM 公开表提供调查观察日，未提供可靠发布日期时保持空值。

## 数据有效性与历史文件

- 缺失、异常字符串、NaN/Infinity、明显占位零、未来日期、过期数据或无来源日期，均标 invalid，`value=null`。
- 日度来源最长允许 7 个日历日；周度最长 14 日。Yahoo 价格与 Above 200MA 更严格：必须对应最近已完成交易日。NYSE 日历处理休市及提前收盘，收盘后留 30 分钟发布缓冲。
- NAAIM 官方公开延迟表是单独的参考状态 `delayed`，显示值和距离观察日的天数。仅该官方地址可以使用此状态，最长接受 110 日（约三个月加周度发布余量）；之后仍为 invalid。其数值须通过同样的非空、有限值、非占位零及范围检查。延迟参考计数独立，绝不增加当前 valid / Bull / Neutral / Bear。
- MA / RSI 历史窗口检查正价格、缺失交易日、重复和乱序；XLY/XLP 比较相同日期。
- Put/Call 最多回看 5 个已完成交易日，以响应日期为准，不能用请求日假充。
- AAII Spread / BTC 涨跌可以合法为负或零；AAII 的 -1 必须能由有效 Bull/Bear/Neutral 分项验证，不能是抓取失败占位。
- invalid 不参与 Bull、Neutral、Bear，Telegram / Discord 显示“⚠️ 数据不可用”。全无效时不形成市场结论，进程退出码为 2，GitHub Actions 会显示失败。
- `data/history.csv`：新验证记录，同一市场交易日更新一行；每列都有对应来源、数据日期、状态、原因。无效值为空；延迟参考保存真实值且 `NAAIM_status=delayed`。分析必须检查状态，不能把 delayed 当当前行情。
- schema 3 新增独立 `Count_delayed`；首次升级时原 schema 2 CSV 备份为 `history_schema2_backup.csv`，保留原有日期行。
- `data/latest.json`：最近一次运行的完整结构化快照及计数。
- `data/history_legacy_unverified.csv`：上游旧历史的原样备份，含已知 0/-1 污染且缺少日期证据，**不能直接用于回测/训练**。首次升级自动隔离；不会覆盖不一致的备份。
- CSV 的 Date 是市场交易日；CNN、AAII、FRED 等须读取各自 `*_data_date`，不是所有指标都来自同一天。旧缓存不伪装为本次抓取成功。

## Telegram 推送

通过 `.env` 或环境变量配置 `TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`，模板中的两项默认留空。本机已经通过一次性 `/start` 标记验证并绑定用户私人会话，不根据机器人历史聊天猜测收件人。

每次 `python main.py` 抓取后自动发送完整报告：包含 15 个指标的值、来源、日期、有效性、原规则判读及计数。长报告按完整指标分段，低于 Telegram 消息长度上限；纯文本发送，不依赖 Markdown 转义。Telegram 与 Discord 独立配置，可只启用 Telegram。

缺少配置时跳过推送，本地采集仍继续。CSV/JSON 先落盘；推送失败令本次进程退出码为 2，但不丢失数据。API 必须确认目标会话才记为 sent。请求超时不自动重试，避免重复发送。Token、chat ID 和响应正文不出现在日志中。

凭据保存在忽略版控、权限 `0600` 的 `.env`，不写进代码。本机运行副本位于 `~/Library/Application Support/DailyStockBot/`，由 `local.daily-stock-bot` LaunchAgent 每天北京时间 **07:00、21:00** 执行。Mac 需要开机、登录并联网，关闭 Codex 或终端不影响任务。

## Discord（可选）

通过环境变量 `DISCORD_WEBHOOK_URL`，或项目内忽略版控的 `.env` 配置（模板见 `.env.example`）。不要写入 Python 文件或提交凭据。

未配置时正常跳过。先保存本地数据再推送；推送失败保留 CSV/JSON，日志仅显示状态码或错误类型，不打印 Webhook URL。尚未配置真实 Webhook，因此真实投递未验证。

## AAII 官方数据

优先读取官方 XLS 和公开调查页。直连调查页受反爬或结构异常影响时，若设置了 `FIRECRAWL_API_KEY`，会通过 Firecrawl 抓取**同一官方页面的原始 HTML**。请求 `maxAge=0`，不读旧抓取缓存，不使用 AI 生成或抽取的指标值。

备用响应必须是 AAII 官方地址、源 HTTP 200，并通过原有 Bull/Bear/Neutral 总和、Spread、调查周及发布日期校验。直连和备用都失败则保持 invalid；不会生成 0/-1。官方 XLS 与调查页同时有效时选择较新的发布日期，同期 Spread 冲突则 invalid。

本机已复用现有 Firecrawl 账户配置；云端运行需另设 `FIRECRAWL_API_KEY` secret。这个备用通道会消耗该服务的现有额度，无法保证永不失效；没有 key 时原有官方直连路径仍可运行。

## NAAIM 最新数据

[NAAIM 官方](https://naaim.org/programs/naaim-exposure-index/) 已将最新周度数据转为订阅：[官方订阅申请](https://members.naaim.org/ap/Membership/Application/GrZAe6L1)，[订阅后登录](https://index.naaim.org/)。程序不绕过登录或付费限制；订阅本身不会自动把数据权限接入本项目。

如果已有合法获取的 NAAIM 导出，可将其规范为以下 CSV，保存至 Git 之外或 `data/private/`，再通过 `NAAIM_CSV_PATH` 指定路径：

```csv
data_date,release_date,value
```

每行填入实际观察日、实际发布日期、真实数值；不附示例行情以免误用。程序仍检查日期、新鲜度、数值范围及零占位。当前选择不订阅，读取公开表并明确标为延迟参考；公开表未提供可靠发布日期，不能把观察日或抓取日当发布日期。

## 定时运行与 GitHub Actions

正式调度由本机 `launchd` 负责，每天北京时间 **07:00 和 21:00**，含周末。`.github/workflows/daily_run.yml` 仅保留手动触发；自动 schedule 已删除，避免两个环境同时推送。

本机每 5 分钟补检查一次，登录时也检查。`schedule_guard.py` 只允许补发最近 3 小时内到期且没有发送记录的报告；已发送或结果不确定的时段会跳过。只读 Telegram 连通性检查失败时不占用时段，网络恢复后可以重试。

运行目录的 `data/delivery_state.json` 保存每个北京时间时段的尝试和结果，不含 token/chat ID。发送前先持久化 `sending` 记录，Telegram 确认后再保存 `sent`。发生请求超时/中断时保持 `uncertain` 或 `sending`，不盲目补发；需核对该次日志后处理。本地文件锁阻止并发运行。GitHub 手动触发使用仓库自身回执，不读取本机数据；本地 `python main.py` 仍可直接按需采集推送。

实际消息在采集完成后发送。Mac 关机或断网时无法准时发送；睡眠唤醒后只在补发窗口内处理。Telegram 标题显示北京时间及计划时段。此前 GitHub active 但无自动事件的问题记录在 [9/18 排查记录](docs/schedule-incident-2026-09-18.md)。

早间报表使用最近已结束的美股交易日。21:00 北京时间通常仍在美股盘前，价格技术指标继续使用最近收盘，CNN 等按各自真实更新时间展示；不把昨天收盘伪装成今晚盘中行情。

- 官方稳定版本：`actions/checkout@v7.0.1`、`actions/setup-python@v7.0.0`，Python 3.11、Ubuntu。
- 先装依赖、pip check、运行回归测试，再采集和可选 Telegram / Discord。
- 声明 `contents: write`，串行保存数据，15 分钟超时。
- 仅提交生成的数据；先提交再 pull --rebase，不在脏工作区直接 git pull，不用 `|| exit 0` 吞掉提交错误。
- Actions Summary 列出值、来源、日期、状态；缺失指标发出 warning。
- 请 fork 到自己的仓库并启用 Actions。Telegram 使用 Repository secrets `TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`；AAII 备用通道使用 `FIRECRAWL_API_KEY`；Discord 可选，使用 `DISCORD_WEBHOOK_URL`。组织策略/分支保护也需允许机器人写入目标分支。不要提交本机 `.env`。
- 代码备份在 [NatureLL666/daily-stock-bot](https://github.com/NatureLL666/daily-stock-bot)，云端手动运行保留。首次 [Ubuntu 手动实跑](https://github.com/NatureLL666/daily-stock-bot/actions/runs/35233636641) 和 9/18 手动补发均确认 Telegram 投递；这些记录不代表自动调度曾经成功。最新本机运行与定时验收见 [本地部署记录](docs/local-deployment.md)，当前回归测试为 124 项。

## 文件结构

沿用 `main.py → config.py / data_fetchers.py / 各指标模块 → utils.py`。新增的 `data_quality.py` 集中数值、日期、来源验证和 HTTP 行为，`telegram_push.py` 处理可选 Telegram 投递，`tests/` 防止错误值重新污染输出。

原阈值和方向规则保留，包括 RSI、VIX、CNN、AAII 等逆向解释。输出是原规则计数，不代表经回测验证的预测能力。
