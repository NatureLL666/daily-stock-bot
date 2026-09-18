# 2026-09-18 早报未送达排查

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

## 证据与边界

初始 API 快照保存在忽略版控的 `evidence/missed-schedule-20260918.json`。回归测试覆盖 UTC 跨日、07:00/21:00、迟到补发、已发去重、不确定结果、缺少配置、损坏记录及跨 run 记录归属。云端补发和真正的 schedule 验证结果在完成后补记。

GitHub 官方明确说明整点高负载时 schedule 可能延迟，严重时会丢弃任务：[官方说明](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)。本次没有内部队列证据，不能据此断言这就是单次遗漏的确切原因；补触发也仍依赖 GitHub 本身可用。
