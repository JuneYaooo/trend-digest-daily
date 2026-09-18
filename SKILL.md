---
name: trend-digest-daily
description: 每天轮询多个公开热榜（微博/知乎/百度/HN 默认，Reddit/GitHub Trending 可选），做标题去重与跨源聚类，对照博主领域配置输出一份每日选题建议 markdown 日报；只读公开接口且每源每次仅 1 个请求，不做全站爬取、不代发内容、热度不跨源比较。当用户要"今天写什么""汇总各平台热点""出每日选题"时使用。
---

# 自媒体每日选题雷达

当用户要"看看今天各平台有什么热点""帮我出今天的选题""做一份热点日报"时使用本 Skill。
交付物是一份去重聚类、对照博主领域、可直接动笔的每日选题建议 markdown，不是热榜转贴面板。

## 工作边界（红线，不可协商）

- 只用公开接口：默认源微博/知乎/百度/HN，可选源 Reddit/GitHub Trending（需代理）。
  每源每次运行**至多 1 个 HTTP 请求**（脚本内已做请求预算硬限制），禁止循环重试、调大频率或全站爬取。
- 热度数值口径互不可比（微博热度值 / 知乎万热度 / HN points / 百度无数值），只在源内比较排名；
  日报必须注明"聚合顺序为 AI 建议"。
- 中文源均为无契约的公开端点，随时可能改版：每源独立降级，单源失败在日报"源状态"如实标注，
  不得静默假装成功。只引用标题与链接，不转载正文。
- 不虚构任何条目、热度数字或链接；一切以 fetch_trends.py 的 JSON 输出为准。

## 默认流程

1. **读配置**：读仓库根目录 `config.yaml`（领域关键词、平台、源开关）。文件不存在或为空 →
   输出通用版（按热度来源数与排名选题，跳过领域匹配）。
2. **拉取热榜**：运行脚本（参数详见 [docs/usage.md](docs/usage.md)）：
   `python3 scripts/fetch_trends.py --output data/trends.json --seen data/seen.jsonl --seen-out data/seen.jsonl`
   断网评测或演示加 `--offline <夹具目录>`；`--date` 固定日期保证可复现。
3. **读规范化 JSON**：按 `sources[].items[]` 理解每源条目（source/rank/title/url/hot_value/
   hot_label/is_new/streak/first_seen/dup_of）。`status=unavailable` 的源记入日报"源状态"。
4. **跨源聚类命名**：`dup_of` 条目并入主条目；标题不同但明显同一事件的（如"男篮惨败"与
   "教练下课"）保守合并为一个话题并列出全部佐证，拿不准就拆开。每个话题命名成一句人话。
5. **领域匹配打分**：对照 config.yaml 关键词给匹配度（规则见
   [references/report-format.md](references/report-format.md)），选出 3-5 个话题写选题卡：
   热度证据（源#排名+标签）、发生了什么、为什么和你有关、可写角度 2-3 个、时效窗口、原帖链接。
6. **渲染日报**：按 [references/report-format.md](references/report-format.md) 的模板输出
   `reports/YYYY-MM-DD.md`，含今日必看 / 次级观察 / 全源速览表 / 趋势追踪（streak≥2 的连续在榜条目）
   与源状态说明。NEW/streak 只能来自 JSON 字段，不得推算。
7. **收尾提醒**：提醒用户发布前点开原帖核实；「爆/热」标签话题建议 24h 内跟进。

支持文件：

- [references/sources.md](references/sources.md)：六个源的端点、字段、实测状态与风险（2026-09-19 实测）。
- [references/report-format.md](references/report-format.md)：日报结构与聚类/打分规则。
- [references/benchmarks.md](references/benchmarks.md)：与 newsnow/RSSHub/DailyHotApi 等的定位对比。
- [docs/usage.md](docs/usage.md)：命令行参数、退出码、crontab 定时与评测复现。
- [evals/README.md](evals/README.md)：评测证据入口。
