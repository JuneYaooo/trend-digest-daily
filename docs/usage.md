# 使用与维护文档

## 命令

每日一次（agent 或手动）：

```bash
python3 scripts/fetch_trends.py --config config.yaml --output data/trends.json --seen data/seen.jsonl --seen-out data/seen.jsonl
```

人类可读摘要写 stderr；不加 `--output` 时 stdout 只有 JSON，可直接管道给 `jq`。

评测 / 断网 / 演示（离线夹具，不联网）：

```bash
python3 scripts/fetch_trends.py --offline evals/fixtures/trends_v1 --date 2026-09-19 \
    --seen evals/fixtures/seen_day1.jsonl --output /tmp/trends.json
```

可选源（失败自动跳过；Reddit 自 2026-05 起拒绝匿名访问，2026-11-02 实测 403）：

```bash
python3 scripts/fetch_trends.py --config config.yaml --sources weibo,zhihu,baidu,hn,github_trending --output data/trends.json
```

## 参数

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--sources` | `weibo,zhihu,baidu,hn` | 逗号分隔；可选 `github_trending`、`reddit` |
| `--config FILE` | 不启用 | 领域配置（`config.yaml`）；给出后每条输出 `domain_hits`，解析失败只告警、跳过匹配 |
| `--hn-mode` | `front` | `front`：读 HN 首页 HTML，rank=首页位置；`algolia`：Algolia front_page，rank=points 顺序 |
| `--limit` | 30 | 每源最多保留条数 |
| `--timeout` | 10 | 单源超时秒数（独立生效；禁止用重试换成功率） |
| `--date` | 今天 | 数据日期（ISO）；评测与复现时固定该值 |
| `--offline DIR` | 不启用 | 离线夹具模式：读 `DIR/{source}.json|.html`，完全不联网 |
| `--reddit-sub` | popular | Reddit 版名（可选源） |
| `--seen FILE` | 不启用 | 已见缓存 JSONL（只读，用于 NEW/streak/first_seen 判定） |
| `--seen-out FILE` | 不启用 | 更新后的缓存输出路径（日常可与 `--seen` 同一路径） |
| `--output FILE` | stdout | 规范化 JSON 输出路径 |
| `--quiet` | 关闭 | 不向 stderr 打印人类可读摘要 |

v0.1.x 的已见缓存可以直接沿用：旧行没有 `last_rank`，第一次运行时 `rank_delta` 为空，之后自动补上。

## 输出结构（规范化 JSON）

顶层：`schema_version（1.1）/ tool_version / fetched_date / mode(live|offline) / sources_enabled /
notes / summary / sources[]`；`summary` 新增 `multi_source_topics`（跨源同发话题数）与
`related_pairs`（同事件候选对数）。

每源：`source / display_name / endpoint / status(ok|unavailable) / error / requests（本源本次实际 HTTP
请求数，恒 ≤1）/ rank_basis（名次含义）/ hot_value_note / skipped（被排除的置顶/广告位：原因→条数）/ items[]`。

每条（v0.1 字段不变，v0.2 新增的用 * 标出）：

| 字段 | 含义 |
| --- | --- |
| `source / rank / title / url / key / extra` | 来源、源内名次、标题、链接、缓存 key、源特有字段（微博 `onboard_time`、HN `num_comments/submitted_at` 等） |
| `hot_value / hot_value_raw / hot_label` | 热度数值（仅源内可比）、原文、标签（新/热/爆…） |
| `is_new / streak / first_seen` | 是否首次出现、连续在榜天数（昨天在榜才 +1）、首见日期 |
| `prev_seen*` / `prev_rank*` / `rank_delta*` | 上次出现日期、上次同源名次、`prev_rank − rank`（正数=上升） |
| `gap_days*` | 断档天数（非空表示"回潮"：之前上过榜，中间消失过） |
| `dup_of / dup_of_title / dup_similarity` | 跨源重复指向的主条目（只在不同源之间判重） |
| `fusion*` | 主条目上：`source_count`、`sources_hit[{source,rank}]`、`rrf_score = Σ 1/(60+rank)`；重复条目为 null |
| `related*` | 主条目上：包含度 ≥0.6 的跨源同事件候选 `[{key,source,rank,containment}]`，只对中文标题计算，不合并 |
| `domain_hits*` | 传 `--config` 时：`[{key,label,matched[]}]` |

## 退出码

| 退出码 | 含义 |
| --- | --- |
| 0 | 成功（至少一个源可用；空榜也算成功） |
| 2 | 参数/IO 错误（未知源、坏日期、夹具目录不存在、文件写入失败） |
| 3 | 全部启用源均不可用（仍输出合法 JSON，逐源中文错误） |

## 定时运行（可选）

本仓库**不内置任何 CI/定时配置文件**。想每天早上自动生成，可自行把一行命令加入系统 crontab
（`crontab -e` 添加，注意替换为你的仓库绝对路径）：

```bash
30 7 * * * cd /path/to/trend-digest-daily && python3 scripts/fetch_trends.py --config config.yaml --output data/trends.json --seen data/seen.jsonl --seen-out data/seen.jsonl --quiet
```

随后让 Agent 读 `data/trends.json` 按 SKILL.md 生成 `reports/YYYY-MM-DD.md`。

## 测试与评测

```bash
python3 -m unittest discover tests            # 40 项单元测试（离线夹具，不联网）
python3 evals/scripts/run_cases.py            # t1-t7、t10-t15 原子检查 → evals/runs_v2/case_results_v2.json
python3 evals/scripts/aggregate_results.py    # 从 judgments_v2 重新聚合 summary_v2.json（--suite v1 复算旧版）
python3 evals/scripts/verify_report.py evals/runs_v2/live_report_2026-11-02.md evals/runs_v2/live_trends_2026-11-02.json
python3 evals/scripts/compare_versions.py --raw <原始响应目录>   # 新旧版本同输入对比（原始响应需自行抓取，未入库）
```

原始响应目录需要的文件：`weibo.json`、`zhihu.json`、`baidu.json`（各自接口的响应体）、`hn.html`（HN 首页）、
`hn.json`（Algolia front_page 响应）、`github_trending.html`。

安装为 Skill（复制到 `~/.codex/skills/trend-digest-daily`，已存在则先备份）：

```bash
bash install_as_skill.sh            # 或 bash install_as_skill.sh <目标 skills 目录>
```

完整评测协议与证据入口见 [evals/README.md](../evals/README.md)。
