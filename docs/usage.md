# 使用与维护文档

## 命令

每日一次（agent 或手动）：

```bash
python3 scripts/fetch_trends.py --output data/trends.json --seen data/seen.jsonl --seen-out data/seen.jsonl
```

评测 / 断网 / 演示（离线夹具，不联网）：

```bash
python3 scripts/fetch_trends.py --offline evals/fixtures/trends_v1 --date 2026-09-19 \
    --seen evals/fixtures/seen_day1.jsonl --output /tmp/trends.json
```

需要代理的可选源（确认代理可用后再启用，失败自动跳过）：

```bash
python3 scripts/fetch_trends.py --sources weibo,zhihu,baidu,hn,reddit,github_trending --output data/trends.json
```

## 参数

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--sources` | `weibo,zhihu,baidu,hn` | 逗号分隔；可选 `reddit`、`github_trending` |
| `--limit` | 30 | 每源最多保留条数 |
| `--timeout` | 10 | 单源超时秒数（独立生效；禁止用重试换成功率） |
| `--date` | 今天 | 数据日期（ISO）；评测与复现时固定该值 |
| `--offline DIR` | 不启用 | 离线夹具模式：读 `DIR/{source}.json|.html`，完全不联网 |
| `--reddit-sub` | popular | Reddit 版名（可选源） |
| `--seen FILE` | 不启用 | 已见缓存 JSONL（只读，用于 NEW/streak/first_seen 判定） |
| `--seen-out FILE` | 不启用 | 更新后的缓存输出路径（日常可与 `--seen` 同一路径） |
| `--output FILE` | stdout | 规范化 JSON 输出路径 |
| `--quiet` | 关闭 | 不向 stderr 打印人类可读摘要 |

## 输出结构（规范化 JSON）

顶层：`schema_version / tool_version / fetched_date / mode(live|offline) / sources_enabled /
notes / summary / sources[]`；每源：`source / display_name / endpoint / status(ok|unavailable) /
error / requests（本源本次实际 HTTP 请求数，恒 ≤1）/ hot_value_note / items[]`；每条：
`source / rank / title / url / hot_value / hot_value_raw / hot_label / is_new / streak /
first_seen / dup_of / dup_similarity / key / extra`。热度口径见各源 `hot_value_note`：仅源内可比。

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
30 7 * * * cd /path/to/trend-digest-daily && python3 scripts/fetch_trends.py --output data/trends.json --seen data/seen.jsonl --seen-out data/seen.jsonl --quiet
```

随后让 Agent 读 `data/trends.json` 按 SKILL.md 生成 `reports/YYYY-MM-DD.md`。

## 测试与评测

```bash
python3 -m unittest discover tests          # 24 项单元测试（离线夹具，不联网）
python3 evals/scripts/run_cases.py          # t1-t7 原子检查 → evals/runs_v1/case_results_v1.json
python3 evals/scripts/aggregate_results.py  # 从 judgments 重新聚合 summary_v1.json
```

完整评测协议与证据入口见 [evals/README.md](../evals/README.md)。
