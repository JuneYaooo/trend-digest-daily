# 夹具说明（fixtures）

本目录所有文件均为**人工编写的合成样本（synthetic fixtures）**：话题、标题、链接、
热度数字全部虚构，仅用于离线评测与单元测试，不对应任何真实热榜内容。
响应体结构与 2026-09-19 实测的各源接口一致（字段见 [references/sources.md](../../references/sources.md)），
但内容不取自真实接口返回。

| 文件/目录 | 用途 |
| --- | --- |
| `trends_v1/` | 主夹具：微博 6 条（含 1 条广告位、话题外壳）、知乎 5 条、HN 5 条（含 1 条无外链）、百度 500 错误体；含两组跨源重复（微博↔知乎） |
| `seen_day1.jsonl` | 2026-09-18 的已见缓存样本：两条与当日榜单重合（一条精确同名、一条标题变体）、一条已冷却未上榜，用于 NEW/streak 判定 |
| `trends_empty_v1/` | 空榜单边界：知乎/HN 返回空列表（状态 ok、0 条），微博空列表按结构异常降级，百度 500 |
| `trends_all_error_v1/` | 全源失败边界：四个源全部返回错误体，脚本应以退出码 3 结束且仍输出合法 JSON |
| `trends_optional_v1/` | 可选源：GitHub Trending HTML 与 Reddit JSON 的合成响应，用于可选源适配器测试（不联网） |
| `trends_optional_v2/` | 回归夹具（2026-09-19 第二次联网回归发现页面改版后新增）：GitHub Trending 条目内含 `/sponsors/{owner}` 赞助按钮（出现在仓库标题链接之前）与 `/sponsors/explore` 链接，断言赞助链接不入条目、仓库按序完整解析 |
