# 评测（Evals V1）

本目录保存 trend-digest-daily 的行为证据：题集、量表、运行协议、真实产物与逐题判断。

## 评测分层

1. **脚本行为层**（t1–t7）：对 `evals/fixtures/` 的合成夹具运行
   `python3 evals/scripts/run_cases.py`，逐条核对 [cases_v1.jsonl](cases_v1.jsonl) 的
   required/forbidden 原子检查（多源聚合、NEW/streak 增量、单源 500 隔离、空榜、全源失败、
   确定性 sha256、Jaccard 去重），结果存 [runs_v1/case_results_v1.json](runs_v1/case_results_v1.json)。
   全程离线，不访问网络。
2. **真实拉取层**（t8）：2026-09-19 在本机（大陆网络）真实抓取四源，每源恰 1 个请求、
   超时 10s，产物 [runs_v1/live_trends_2026-09-19.json](runs_v1/live_trends_2026-09-19.json)
   （120 条 → 去重 119，含 1 组真实跨源重复）。
3. **Agent 工作流层**（t9）：Agent 依 [references/report-format.md](../references/report-format.md)
   把当日 JSON 渲染为 [runs_v1/live_report_2026-09-19.md](runs_v1/live_report_2026-09-19.md)；
   报告引用的 URL 与热度数字经脚本回核全部存在于 JSON。另附合成夹具演示日报
   [runs_v1/demo_report_2026-09-19.md](runs_v1/demo_report_2026-09-19.md)（含连续在榜场景）。

## 当前状态（2026-09-19，v0.1.0）

- **9/9 用例通过，0 硬失败**；单元测试 22/22 通过。逐题判断见
  [judgments_v1.jsonl](judgments_v1.jsonl)，机器汇总见 [summary_v1.json](summary_v1.json)
  （由 [scripts/aggregate_results.py](scripts/aggregate_results.py) 从 judgments 重新计算）。
- 三轮真实失败与修复见 [iteration_notes.md](iteration_notes.md)：真实接口首跑发现百度热度字段
  误读与知乎标签代码；单测抓到已见缓存对标题变体条目重复膨胀；均已修复并加回归断言。
- **第二次联网回归（2026-09-19 下午，v0.1.1）**：四源结构与首跑一致、全部可用；带 seen 连续两跑
  （间隔约 3 分钟）验证增量：120 条全量 NEW → 116 已见 + 3 NEW，缓存无膨胀；Reddit 超时如实
  标注"源不可用"；GitHub Trending 页面新增赞助链接致旧适配器混入 1 条假条目，已修复并加回归
  测试（单测 22→24）。产物：[runs_v1/](runs_v1/) 下 `regression_2026-09-19_*`（含终端记录）。
- 夹具全部为合成样本（见 [fixtures/README.md](fixtures/README.md)），话题、链接、热度均为虚构；
  真实拉取产物中的热榜条目版权归原作者，仅按标题与链接引用。
- 已知限制：判定为开发 Agent 自评（model_only），未独立人工复核；跨语言同事件依赖 agent
  保守聚类；中文源接口无契约，随时可能改版（见 references/sources.md 的每源风险）。

## 复现

命令与参数见 [docs/usage.md](../docs/usage.md)。评测脚本层全程离线，无需任何 API 密钥。
