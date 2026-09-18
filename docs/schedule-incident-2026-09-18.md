# 2026-09-18 早报未送达排查

后续处理：用户确认 Mac 基本不关机，选择改为本地定时。已通过 10:27 的真实 macOS 定时触发和 Telegram 投递验收，GitHub 自动 schedule 停用，见 [本地部署记录](local-deployment.md)。这解决了当前推送的调度路径，不表示 GitHub 原调度问题已被修复。

## 已确认的事实

- 08:06 北京时间核查时，工作流处于 active，仓库 Actions enabled，默认分支 main，未归档或禁用。
- 当时远端 cron 是 `0 13,23 * * *`（UTC）。23:00 UTC 对应次日 07:00 北京时间，13:00 UTC 对应当日 21:00，换算正确。
- GitHub API 的 `event=schedule` 运行总数为 **0**；只存在 9/17 的一次成功 `workflow_dispatch` 手动测试。今早没有进入抓取或 Telegram 步骤。
- 因而故障定位在定时任务创建之前，不是日志已经证明的 Telegram 发送失败。GitHub 未公开单次漏触发的内部原因，不能把新 fork 注册、整点负载或平台故障当作已证实根因。
- 昨天的验收只覆盖了手动云端运行，未覆盖真正的 schedule 事件，验收范围不足。

## 修复

- 显式使用 `Asia/Shanghai` 的 07:00/21:00 两个目标时段。
- 保留整点触发，增加两小时内的错峰补检查，不移动用户要求的目标时间。
- 增加标准库 `schedule_guard.py`：到期判定、3 小时补发窗口、按日期和时段的独立发送记录、跨日与重复触发检查。
- 发送前先将尝试记录提交到仓库；Telegram API 确认后记 sent；发送结果不确定时不自动重复发送。
- 已完成时段的补检查在安装依赖及抓取之前跳过，保持原有 15 指标、有效性判定及 NAAIM 延迟参考口径。
- Telegram 显示实际北京时间和计划时段。
- 08:30:57 北京时间完成一次显式 disable/enable 刷新，API 确认状态按 active → disabled_manually → active 变化。此项用于排除启用状态注册异常，不代表已证明原遗漏的内部原因。

## 证据与边界

初始 API 快照保存在忽略版控的 `evidence/missed-schedule-20260918.json`。本地及 GitHub Actions Ubuntu 均通过 **118 项测试**，覆盖 UTC 跨日、07:00/21:00、迟到补发、已发去重、不确定结果、缺少配置、损坏记录及跨 run 记录归属。

- 08:17:15 北京时间，[补发运行 35290501575](https://github.com/NatureLL666/daily-stock-bot/actions/runs/35290501575) 成功，Telegram API 确认向已绑定会话发送 1 条报告。该次是 `workflow_dispatch`，不能当作自动触发证明。
- 仓库已保存 `2026-09-18T07:00:00+08:00` 的 `sent` 回执。本地读取相同回执，确认后续检查返回 `send=False`，不会重复发送这一期。
- 截至 **08:46:46 北京时间**，仓库 `event=schedule` 运行总数仍为 **0**；自动定时仍未验收通过，不能宣布恢复，也不能承诺今晚已能自动送达。
- 临时最小 UTC 探针在 08:37:52 注册为 active（workflow ID `360974401`，commit `19a67f7`）：仅 `*/5 * * * *` 和输出 UTC 时间，无依赖安装、行情采集或通知凭据。在上述检查时点也未产生自动事件。这是有限观察窗口，不能据此断言 GitHub 内部的确切故障。
- 观察结束后已停用并移除临时探针，正式工作流保持 active。最终 API 快照为 `evidence/schedule-final-observation-20260918.json`。没有创建本机替代任务或新的第三方调度服务。

本轮可以确认应用采集、补发、发送回执及去重正常；不能确认 GitHub 自动调度恢复。已排除 UTC 换算、默认分支缺失、工作流显式禁用和 Telegram 发送链路失败。若后续仍无 schedule 事件，可将本记录中的仓库、workflow ID、原/现 cron、时间及成功手动 run ID 提供给 GitHub Support 检查调度注册/队列；公开 API 无法直接检查其内部状态。

## 本期数据质量

08:17 补发快照为 **8/15 valid、6 invalid、1 delayed**，Bull 3 / Neutral 3 / Bear 2。与 9/17 手动验收的 14/15 是不同时点，不应混用。

只读复查 Yahoo 返回结果：HYG、IWM、SOXX、XLY 和 XLP 的 9/17 收盘行为空；BTC 缺少 9/17 完整日线，仅有 9/16 和 9/18 未完成日线。前述 5 个指标（XLY/XLP 合计一项）因此无效。Above 200MA 仍停在 9/16，未满足最新完整交易日校验。它们没有用旧收盘或盘中值代替，也未参与统计。NAAIM 公共表更新为 6/17 的 92.83，保持 delayed、原观察日和 93 天延迟，不参与投票。此次未改数据判定或多空算法。

GitHub 官方明确说明整点高负载时 schedule 可能延迟，严重时会丢弃任务：[官方说明](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)。本次没有内部队列证据，不能据此断言这就是单次遗漏的确切原因；补触发也仍依赖 GitHub 本身可用。
