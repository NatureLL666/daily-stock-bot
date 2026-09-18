# 本地定时推送

2026-09-18 按用户选择迁为 macOS 本地运行。正式任务标签为 `local.daily-stock-bot`，使用系统 `launchd`，不依赖 Codex、终端或浏览器窗口。

## 时间与运行条件

- 每天北京时间 07:00、21:00，含周末。
- 本机系统时区已核对为 Asia/Shanghai，程序也按北京时间判断时段。
- 每 5 分钟额外检查一次；只补发最近 3 小时内到期且尚未尝试发送的时段，登录时也检查。
- 需要 Mac 开机、登录当前用户并联网；锁屏可以继续执行。关机不能发送，睡眠期间不能保证按时发送，唤醒后在补发窗口内再检查。
- 当前网络通道是已有 Karing 代理服务，已确认独立于 Codex；需保持 Karing 服务可用。它尚未就绪时，连通性预检失败会保留时段供后续重试。
- 采集完成后发送，所以消息时间略晚于计划时间。网络和数据源异常仍会明确标记。

## 运行位置

运行目录：`~/Library/Application Support/DailyStockBot/`。

| 文件 | 用途 |
|---|---|
| `.venv/bin/python`、`python/` | 独立 Python 3.11 及依赖，不指向 Documents 下的项目 |
| `.env` | Telegram、AAII 备用通道和已有网络代理配置，权限 0600 |
| `data/history.csv`、`data/latest.json` | 本地累计历史和最近数据快照 |
| `data/delivery_state.json` | 每个早晚时段的发送回执，迁移时保留已有成功记录 |
| `data/private/last_check.json` | 最近调度检查的时间及结果 |
| `data/private/last_run.json` | 最近真实采集运行的退出码、回执和日志位置 |
| `logs/run-*.log` | 每次完整采集和投递日志 |
| `logs/launchd.log`、`logs/launchd-error.log` | 系统调度启动日志 |

LaunchAgent 配置：`~/Library/LaunchAgents/local.daily-stock-bot.plist`。运行目录权限 0700，配置不含 Telegram token 或 chat ID。

仓库是开发源代码，运行目录是实际执行副本。本地历史在运行目录持续追加，不自动向公开仓库上传本机配置或日志。修改源代码后，需通过安装脚本更新运行副本；该脚本保留已有历史、发送回执和凭据。

## 发送保护

本地文件锁阻止同时运行两个采集进程。到期后先调用 Telegram 的只读 getMe 检查连通性；断网或代理未就绪时不占用发送时段，后续检查可以重试。每次采集子进程最多运行 15 分钟。发送前持久化尝试记录，收到 Telegram API 成功确认后才记为 sent。发送超时或中断后保留 uncertain/sending，不盲目重发。

原 15 项指标、有效性验证、CSV 格式、多空规则和 NAAIM 延迟参考口径不变。

## 云端状态

`.github/workflows/daily_run.yml` 删除自动 schedule，保留 workflow_dispatch 手动运行。日常定时发送只有本机这一处，避免 GitHub 调度恢复后双重发送。手动云端运行使用仓库内的历史与回执，不会自动读取本机的新数据。

## 安装和核查

从源代码目录使用现有 Python 3.11：

```bash
.venv/bin/python scripts/install_launch_agent.py
launchctl print gui/$(id -u)/local.daily-stock-bot
```

验收应包含真实 `StartCalendarInterval` 触发的临时测试、Telegram API 确认、运行目录 CSV/JSON 更新，以及正式任务的 07:00/21:00 配置和启用状态。不能只凭 `launchctl` 显示已加载就宣布发送成功。

## 2026-09-18 验收结果

- 独立 Python 3.11.16 安装及 `pip check` 成功；17 个程序/依赖声明文件与源代码哈希一致，Python 基础目录和 venv 均位于运行目录，不指向 Documents 项目。
- 124 项回归测试通过，包含本地文件锁、断网不占用时段、到期判定、成功去重和异常中断记录。
- 临时验收任务只配置 `StartCalendarInterval=2026-09-18 10:27`，未设置 RunAtLoad，也未调用 kickstart。
- macOS 实际在 **10:27:04** 启动任务，**10:27:52** 完成。退出码 0；Telegram API 确认向已绑定会话发送 1 条报告。
- 本期 **12/15 valid、2 invalid、1 delayed**，Bull 5 / Neutral 2 / Bear 5；CSV/JSON 写入独立运行目录。此验收报告不伪装成 07:00 或 21:00 的正式期次。
- 本期不可用项是 BTC（缺完整日线）和 Above 200MA（来源仍为 9/16）；NAAIM 为 6/17 的公开延迟数据。它们按原校验规则排除，未为增加有效指标数而放宽标准。
- 正式任务为 `local.daily-stock-bot`，配置 07:00、21:00 加每 5 分钟检查；初次启动正常退出且未重复发送今早报告。临时验收任务完成后移除。

本地证据位于源代码项目的忽略目录：`evidence/local-launchd-acceptance-plan.json` 和 `evidence/local-launchd-acceptance-result.json`。这是一次真实系统定时触发、真实抓取和真实 Telegram 投递的验证；未来 07:00/21:00 的实际发送仍受本机开机、登录和网络条件约束。
