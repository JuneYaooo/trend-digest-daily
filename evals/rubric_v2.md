# trend-digest-daily 评测量表 V2（v0.2.0）

在 [rubric_v1.md](rubric_v1.md) 基础上，按 v0.2.0 的逻辑改进补充硬失败与原子检查口径；
五个打分维度与 0–4 锚点不变（见 V1）。

## 硬失败（critical failure）

V1 的四条继续有效：任一源单次请求 >1 / 编造条目数字链接 / 把 AI 聚合顺序冒充官方排名 / 静默降级。
V2 新增：

- 跨源相加、换算或比较 `hot_value`（只允许用名次与 `fusion.rrf_score`）；
- 把 `related` 同事件候选不经确认直接合并，或把不同事件合并成一个话题；
- 把置顶位、广告位（`skipped`）当成榜单名次写进日报；
- HN 用 points 顺序却称为"首页第 N"（必须与 `rank_basis` 一致）；
- 没有任何 `domain_hits` 的话题被写成 ★★★ 以上，或星级与 `domain_hits` 不符且没有说明理由。

## 脚本层原子检查口径（新增）

- 名次：每源 `rank_basis` 说明名次含义；HN 默认是首页真实位置；百度置顶、微博广告、HN 招聘帖、
  Reddit 置顶计入 `skipped`，不占名次。
- 去重：只在不同源之间判重（同一榜单内不互相合并）；阈值同 V1。
- 同事件候选：中文标题字符 2-gram 包含度 ≥0.6（短标题 ≥4 个汉字）→ `related`，不合并；英文不计算。
- 融合：`fusion.rrf_score = Σ 1/(60+rank)`，主条目汇总自身与重复条目各源的最好名次。
- 已见缓存：上次出现为昨天 streak+1；同日复跑不变；断档重置为 1 并给 `gap_days`；同源时给 `prev_rank`/`rank_delta`。
- 领域命中：中文子串；全大写 ASCII 缩写区分大小写并检查边界（允许 OpenAI/ChatGPT/xAI，拒绝 Complain/AIGC）；
  其他英文词不区分大小写、只要求左边界。
- 输出：stdout 只有 JSON，摘要写 stderr。

## 通过口径

- 脚本层（t1–t7、t10–t15）：全部原子检查通过（runs_v2/case_results_v2.json）。
- 真实拉取与前后对比（t16）：四个默认源 ok 且每源 requests=1；对比结论来自 runs_v2/before_after_2026-11-02.json。
- Agent 层（t17）：无硬失败，五维均值 ≥3.0，且 verify_report.py 回核 0 问题。
- 未运行的用例必须标注 `not run`。
