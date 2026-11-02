# 评测（Evals）

本目录保存 trend-digest-daily 的行为证据：题集、量表、运行协议、真实产物与逐题判断。
当前版本 v0.2.0 的评测是 V2（`*_v2.*`、`runs_v2/`）；V1（`*_v1.*`、`runs_v1/`）是 v0.1.x 的历史证据，原样保留。

## V2（2026-11-02，v0.2.0）

| 层 | 用例 | 怎么跑 | 证据 |
| --- | --- | --- | --- |
| 脚本行为 | t1–t7（V1 用例原样重跑）+ t10–t15（新逻辑） | `run_cases.py`，离线合成夹具 | [runs_v2/case_results_v2.json](runs_v2/case_results_v2.json) |
| 真实拉取 + 改前改后对比 | t16 | 2026-11-02 大陆网络各源 1 次请求；同一份原始响应分别交给 v0.1.1 与 v0.2.0（`compare_versions.py`） | [before_after_2026-11-02.json](runs_v2/before_after_2026-11-02.json)、[live_trends_2026-11-02.json](runs_v2/live_trends_2026-11-02.json)、[终端记录](runs_v2/live_2026-11-02_terminal.txt)、[可选源](runs_v2/live_optional_2026-11-02.json) |
| Agent 日报 | t17 | Claude Code（Claude Opus 5.5）依 SKILL.md 生成日报，`verify_report.py` 回核 | [live_report_2026-11-02.md](runs_v2/live_report_2026-11-02.md)、[report_check_2026-11-02.json](runs_v2/report_check_2026-11-02.json) |

结果：

- **改前改后（t16，同一输入）**：HN 名次与首页真实位置的 Spearman ρ **−0.27 → 1.0**；同源误并 **1 → 0**；
  百度#1 从置顶政务条目变为自然位；断档 3 天后 streak **2 → 1**（新增 gap_days=3）；
  不加 `--output` 时 stdout **不是 JSON → 是 JSON**；ASCII 关键词差异 6 处，均为旧口径多出的子串命中（5 处明显误命中）；
  新增同事件候选：当天 1 对，对 2026-09-19 入库数据重算 11 对（都属同一事件群）。
- **脚本层**：13/13 用例、全部原子检查通过；单元测试 40/40。
- **Agent 层（t17）**：5 张选题卡，报告中 6 个链接、44 处名次/热度引用全部能在当日 JSON 找到（verify_report 0 问题）。
- 汇总（[summary_v2.json](summary_v2.json)，由 [judgments_v2.jsonl](judgments_v2.jsonl) 计算）：15/15 通过，0 硬失败。
  这个通过率只说明"没有违反量表"，**不是选题质量分**；有意义的是上面的改前改后差异。
- 量表 [rubric_v2.md](rubric_v2.md)、题集 [cases_v2.jsonl](cases_v2.jsonl)、协议 [protocol_v2.json](protocol_v2.json)。

限制（如实说明）：

- 判定为开发 Agent 自评（model_only），未独立人工复核。
- 对比用的原始响应含第三方摘要与用户名，没有入库，只记录 sha256；别人无法逐字节复现，只能用自己当天的响应重跑。
- `rank_delta`、连续在榜、回潮没有在真实多日数据上验证，只用了合成缓存（t13）和模拟日期（t16）。
- 当天日报的缓存来自同日 v0.1.1 首跑，旧缓存没有 `last_rank`，所以日报里没有名次变化。
- Reddit 实测 403，没有可评测的数据。

## V1（2026-09-19，v0.1.0 / v0.1.1，历史）

1. **脚本行为层**（t1–t7）：合成夹具，结果 [runs_v1/case_results_v1.json](runs_v1/case_results_v1.json)。
2. **真实拉取层**（t8）：四源各 1 请求，[runs_v1/live_trends_2026-09-19.json](runs_v1/live_trends_2026-09-19.json)（120 条 → 去重 119）。
3. **Agent 工作流层**（t9）：[runs_v1/live_report_2026-09-19.md](runs_v1/live_report_2026-09-19.md)、合成演示 [runs_v1/demo_report_2026-09-19.md](runs_v1/demo_report_2026-09-19.md)。
4. 第二次联网回归（同日下午）：`runs_v1/regression_2026-09-19_*`。
5. 汇总 [summary_v1.json](summary_v1.json)：9/9 通过；量表 [rubric_v1.md](rubric_v1.md)；协议 [protocol_v1.json](protocol_v1.json)。

注意：V1 日报中的 "HN#N" 是 Algolia 的 points 顺序，不是首页位置（v0.2.0 才修正，见 [iteration_notes.md](iteration_notes.md) 迭代 6）。

## 迭代记录

所有真实失败、归因与修复：[iteration_notes.md](iteration_notes.md)（迭代 6 是本轮基于外部调研的逻辑审查与问题清单）。

## 复现

命令与参数见 [docs/usage.md](../docs/usage.md)。脚本层全程离线，无需任何 API 密钥。
