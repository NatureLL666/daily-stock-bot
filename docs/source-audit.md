# 数据源审计（2026-09-17）

本次先以真实响应复现，再更换抓取方式。所列值仅为审计时点的证据；本机最终输出以 `data/latest.json` 为准。

| 指标/路径 | 原问题及证据 | 修复与当前边界 |
|---|---|---|
| 10Y | Google Finance 已跳转新版；旧 `div.YMlKec.fxKbKc` 匹配数为 0。旧代码固定除以 10 | [FRED DGS10 CSV](https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10) 返回 2026-09-15 = 5.00%，无缩放。曾遇超时，回退 [Yahoo ^TNX](https://finance.yahoo.com/quote/%5ETNX/history/) 的已完成日 2026-09-16 = 5.006%。两者观察日及定义有差异，不伪装为同一报价 |
| SKEW | Google 旧选择器匹配数为 0，历史 CSV 连续记 0 | [CBOE SKEW CSV](https://cdn.cboe.com/api/global/us_indices/daily_prices/SKEW_History.csv)，2026-09-16 = 145.95 |
| NAAIM | 旧 Bricks shortcode ID 已消失，数据改为 iframe；[官方公告](https://naaim.org/programs/naaim-exposure-index/) 声明 2026-08-01 起订阅、公开数据延迟三个月 | 按用户选择使用[公开周度表](https://index.naaim.org/embeddable/table)：2026-06-10 = 79.27，9/17 时延迟 99 天。保存并展示为 delayed 历史参考，不参与当前多空统计，不能声称最新一期；超过 110 日或数值异常时 invalid。公开表没有可靠发布日期，该字段保持空值 |
| AAII | StockQ 原首行截至 2026-08-05，页面还含未来日期；不能信任首行或全页最大日期。官方直连随后返回 HTTP 200 的反爬页 | [AAII 官方 XLS](https://www.aaii.com/files/surveys/sentiment.xls) 和 [调查页](https://www.aaii.com/sentimentsurvey)。9/17 新增可选 Firecrawl 原始 HTML 传输，实时 `maxAge=0` 成功，验证到 9/17 发布、9/16 周截止、Bull 28.8%、Bear 53.3%、Spread -24.5pp。不使用先前本地缓存或 AI 提取值；需要服务额度，仍有反爬及页面变更风险 |
| Put/Call | 原代码可读 TOTAL，但丢失回溯日期；CBOE 已换新地址/前端 | [CBOE daily](https://www.cboe.com/markets/us/options/market-statistics/daily?dt=2026-09-16) 的页面内 JSON：TOTAL=0.98、EQUITY=0.69。严格选 TOTAL 并核对 selectedDate；5 个已结束交易日回溯 |
| Fear & Greed | 原第三方页面价格 CSS 无可靠日期，requests 直连 CNN 可能 HTTP 418 | [CNN JSON](https://production.dataviz.cnn.io/index/fearandgreed/graphdata) 使用匹配的 HTTP 客户端请求头；读取 timestamp 而非本地日期。仍可能被限流，失败为 invalid |
| VIX | 原 Yahoo 路径无明确报价日期，可能取未完成日 | [CBOE VIX CSV](https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv)，读取 DATE/CLOSE |
| Above 200MA | Barchart 直接请求返回 HTTP 202 / JS challenge，不能稳定取得实时 DOM | [TradingView INDEX:S5TH](https://www.tradingview.com/symbols/INDEX-S5TH/) 的公开 daily_bar JSON：50.09、2026-09-16，与此次 Barchart 页面快照一致；校验 symbol、定义及最新完整交易日。没有正式版本化 API，结构变更风险保留 |
| Yahoo 技术指标 | 直接取最后一行可能包含当日未完成 K 线，缺失/NaN 不充分校验 | 用原公式、已完成交易日、完整窗口和同日对齐；保留数据日期和真实失败状态 |
| CSV 清洗 | 实际复现 `錯誤: HTTP 403; driver exit 0` 被写为数值 403 | 全字符串数值验证，错误字符串不会再抽出数字 |
| 多空统计 | 实际复现 BOND_10Y/NAAIM/SKEW 的字符串 “0” 都判为 Bull | 强制验证对象进入判读；invalid 同时排除 Bull/Neutral/Bear；零有效时不输出多空结论 |

没有将第三方社媒情绪、模型生成值或非对应指数用于填补缺口。没有进行交易、配置系统服务或启用本地后台常驻任务。

工作流版本通过 GitHub 官方 release API 及 action.yml 校验：
[checkout v7.0.1](https://github.com/actions/checkout/releases/tag/v7.0.1)、
[setup-python v7.0.0](https://github.com/actions/setup-python/releases/tag/v7.0.0)，均为 Node 24 action，使用 GitHub 托管 Ubuntu runner。

测试用 fixture 是上述真实公开响应的必要片段，固定在 2026-09-17，用于检查解析和日期边界，不被生产抓取代码读取。完整抓取底稿和本机日志在忽略版控的 `evidence/`、`.firecrawl/` 中。
