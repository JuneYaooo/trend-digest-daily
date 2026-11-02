---
name: trend-digest-daily
description: 每天轮询多个公开热榜（微博/知乎/百度/HN 默认，GitHub Trending 可选），做跨源去重、按名次融合排序（RRF）、标出同事件候选与连续在榜/名次上升，再对照博主领域关键词输出一份每日选题建议 markdown 日报；只读公开接口且每源每次仅 1 个请求，不做全站爬取、不代发内容、热度不跨源比较。当用户要"今天写什么""汇总各平台热点""出每日选题"时使用。
---

# 自媒体每日选题雷达

当用户要"看看今天各平台有什么热点""帮我出今天的选题""做一份热点日报"时使用本 Skill。
交付物是一份去重聚类、对照博主领域、可直接动笔的每日选题建议 markdown，不是热榜转贴面板。

## 工作边界（红线，不可协商）

- 只用公开接口：默认源微博/知乎/百度/HN，可选源 GitHub Trending 与 Reddit（Reddit 自 2026-05
  起拒绝匿名 .json 访问，2026-11-02 实测 HTTP 403，保留适配器但默认不用）。
  每源每次运行**至多 1 个 HTTP 请求**（脚本内已做请求预算硬限制），禁止循环重试、调大频率或全站爬取。
- 热度数值口径互不可比（微博热度值 / 知乎万热度 / HN points / 百度无数值），跨源只用名次
  （脚本的 `fusion.rrf_score`）；日报必须注明"聚合顺序为 AI 建议"。
- 中文源均为无契约的公开端点，随时可能改版：每源独立降级，单源失败在日报"源状态"如实标注，
  不得静默假装成功。只引用标题与链接，不转载正文。
- 不虚构任何条目、热度数字或链接；一切以 fetch_trends.py 的 JSON 输出为准。

## 默认流程

1. **读配置**：仓库根目录 `config.yaml` 是博主的领域关键词与平台。存在就在下一步传 `--config`；
   不存在或脚本在 `notes.domain_matching` 里报告无法解析 → 输出通用版（按 `fusion.rrf_score` 选题）。
2. **拉取热榜**：运行脚本（参数详见 [docs/usage.md](docs/usage.md)）：
   `python3 scripts/fetch_trends.py --config config.yaml --output data/trends.json --seen data/seen.jsonl --seen-out data/seen.jsonl`
   断网评测或演示加 `--offline <夹具目录>`；`--date` 固定日期保证可复现。摘要在 stderr，stdout 只有 JSON。
3. **读规范化 JSON**：按 `sources[].items[]` 理解每源条目（source/rank/title/url/hot_value/hot_label/
   is_new/streak/first_seen/rank_delta/gap_days/dup_of/related/fusion/domain_hits）。每源的
   `rank_basis` 说明名次含义，`skipped` 是被排除的置顶/广告位；`status=unavailable` 记入"源状态"。
4. **跨源聚类命名**：`dup_of` 条目并入主条目；`related` 里的候选读标题确认是同一事件才合并
   （如「郭士强 下课」与知乎「…网友称让郭士强下课」），并列出全部佐证，拿不准就拆开。
   每个话题命名成一句人话。
5. **领域匹配打分**：只根据 `domain_hits` 给匹配度星级（规则见
   [references/report-format.md](references/report-format.md)），同星级按 `fusion.rrf_score` 排，
   选出 3-5 个话题写选题卡：热度证据（源#排名+标签）、发生了什么、为什么和你有关（写出命中的关键词）、
   可写角度 2-3 个、时效窗口（参考标签、`rank_delta` 上升、`streak`）、原帖链接。
   关键词命中但语义无关的可以降级，必须写明理由；没有命中的话题不得写成高匹配。
6. **渲染日报**：按 [references/report-format.md](references/report-format.md) 的模板输出
   `reports/YYYY-MM-DD.md`，含今日必看 / 次级观察 / 全源速览表 / 趋势追踪（streak≥2 的连续在榜条目
   与 gap_days 非空的回潮条目）与源状态说明。NEW/streak/rank_delta 只能来自 JSON 字段，不得推算。
7. **收尾提醒**：提醒用户发布前点开原帖核实；「爆/热」标签话题建议 24h 内跟进。

支持文件：

- [references/sources.md](references/sources.md)：六个源的端点、字段、实测状态与风险（2026-11-02 复测）。
- [references/report-format.md](references/report-format.md)：日报结构与聚类/排序/打分规则。
- [references/benchmarks.md](references/benchmarks.md)：对标（TrendRadar/newsnow/DailyHotApi/BuzzSumo 等）、
  方法依据（RRF、HN 排名、Broder 包含度）与本项目差距。
- [docs/usage.md](docs/usage.md)：命令行参数、退出码、crontab 定时与评测复现。
- [evals/README.md](evals/README.md)：评测证据入口。
