# 对标与参考逻辑（2026-11-02 调研，v0.2.0）

调研方式：公开网页、官方文档、开源仓库源码阅读，加上对各数据源的真实请求实测。
star 数为 2026-11-02 经 api.github.com 查询的数值；检索日期均为 2026-11-02（另注明的除外）。
引用内容版权归原作者，本仓库没有复制任何第三方代码，只借鉴思路并在下文注明出处。
初版（2026-09-19）的需求证据与定位结论保留在文末。

## 一、对标清单

| 对标 | 类型 | 它怎么做（与本项目相关的部分） | 可借鉴 | 本项目的差异 |
| --- | --- | --- | --- | --- |
| [sansan0/TrendRadar](https://github.com/sansan0/TrendRadar)（63,365★，GPL-3.0） | 开源，中文热点监控 + 推送 | 数据取自 newsnow 公共 API；按关键词组筛选（普通词、`+`必须词、`!`过滤词、`/正则/`，统一小写后**子串匹配**）；排序权重 `rank 0.6 + frequency 0.3 + hotness 0.1`，其中名次分 `11 − min(rank,10)`、频次是同一标题被多次抓到的次数、hotness 是进前 N 名的比例（`trendradar/core/analyzer.py`、`config/config.yaml`、`trendradar/core/frequency.py`） | **只用名次、不碰各源热度数值**来排序；频次（多次出现）作为热度信号 | 依赖第三方聚合 API；关键词子串匹配会把 "AI" 命中到 "Complain"；没有跨天的连续在榜与回潮概念；不产出选题卡 |
| [newsnext/newsnow](https://github.com/newsnext/newsnow)（22,215★） | 开源，实时热榜阅读器 | `server/sources/*.ts`：HN **直接解析首页 HTML** 的 `.athing` 行（失败才退到 hnrss）；百度解析页面内嵌数据并**过滤 `isTop` 置顶**；微博解析 `s.weibo.com` 热搜页（带固定 cookie）；知乎用 v3 web 接口 | HN 用首页真实顺序、百度去置顶 | 是阅读器：不做跨源去重、领域匹配和选题建议；需要常驻部署 |
| [imsyy/DailyHotApi](https://github.com/imsyy/DailyHotApi)（4,104★） | 开源，热榜 API 聚合 | `src/routes/*.ts`：知乎用与本项目相同的 `api.zhihu.com/topstory/hot-lists/total`；微博用 `ajax/side/hotSearch`；HN 同样解析首页 HTML | 确认知乎老接口仍是社区主流选择；HN 首页解析是通行做法 | 只做聚合展示；微博 `side/hotSearch` 在本项目 2026-09-19 实测已拒匿名 |
| [DIYgod/RSSHub](https://github.com/DIYgod/RSSHub)（46,774★） | 开源，RSS 生成 | 把各站内容转成 RSS，部分中文路由需要 cookie | — | 不负责后续的去重、排序和选题 |
| [BuzzSumo Trending](https://help.buzzsumo.com/en/articles/1633344-trending-now-what-is-the-trending-score) | 商业（$199/月起） | Trending Score 是"随时间的分享速度"（专有公式），Trending Now 只看过去 24 小时 | **速度（velocity）比绝对量更能说明"正在火"** | 不含中文平台；本项目没有分享数，只能用"名次变化"近似速度 |
| [Google Trends 相关查询](https://support.google.com/trends/answer/4355000) | 商业/免费 | Rising 显示相对上一时段的增幅，增幅 >5000% 标 "Breakout"；Google 自己提醒这是相对值、基数可能很小 | 用"相对上次"的变化标注上升，并提醒基数问题 | 本项目用的是榜单名次而不是搜索量 |
| 今日热榜 tophub.today（据 [爱范儿介绍](https://www.ifanr.com/app/1207119)，未逐项核实当前版本） | 商业/免费，中文热榜聚合 | 多平台榜单聚合、订阅，可看各平台上榜历史，追踪器/过滤器为 PRO 功能 | "上榜历史"对应本项目的连续在榜/回潮 | 不做选题建议 |
| [LobsterAI daily-trending](https://tessl.io/registry/skills/github/netease-youdao/LobsterAI/daily-trending/review)、[tophub-trends](https://claudeskills.info/skills/aiskillstore/marketplace/tophub-trends/) | 同类 Agent Skill | 前者逐平台抓 tophub 页面、只保留事实条目，Tessl 评审指出没有去重/排序、日期写死、不校验抓取结果；后者抓 TopHub Top 30 交给 Claude 出选题，需要自备 API Key | 反面清单：必须校验抓取结果、日期不能写死 | 本项目在脚本层做去重、排序、缓存，agent 只做判断与表达 |

## 二、方法依据

| 方法 | 出处 | 结论 | 本项目用法 |
| --- | --- | --- | --- |
| Reciprocal Rank Fusion | Cormack, Clarke & Büttcher, SIGIR 2009，[论文 PDF](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf) | `score = Σ 1/(k+rank)`，k=60 在试点中确定、此后不再调整；只用名次，适合合并分数尺度不同的列表；多篇二手资料指出 k 不敏感 | `fusion.rrf_score`，k=60。各源热度口径不可比，用名次融合正好绕开这个问题。k=60 时上榜源数的影响大于名次差，等于"跨源同发优先" |
| HN 排名公式 | [Ken Shirriff：How Hacker News ranking really works](https://www.righto.com/2013/11/how-hacker-news-ranking-really-works.html)、[Inside the news.yc ranking formula](https://www.righto.com/2009/06/how-does-newsyc-ranking-work.html) | 首页按 `(points−1)^0.8/(T+2)^1.8` 加各种惩罚排序，"#1 不一定是分数最高的" | 说明 Algolia 的 points 顺序不是首页顺序；实测见下 |
| HN robots.txt | https://news.ycombinator.com/robots.txt（2026-11-02 读取） | 首页 `/` 允许抓取，`Crawl-delay: 30` | 每天 1 次请求，远低于限制 |
| 文档相似度与包含度 | Broder 1997《On the Resemblance and Containment of Documents》，[Princeton COS 435 讲义](https://www.cs.princeton.edu/courses/archive/spring15/cos435/notes/duplicateDocs_topost.pdf) | resemblance = Jaccard；containment = \|S(A)∩S(B)\|/\|S(A)\|，专门处理"短文本整段出现在长文本里"，此时 Jaccard 很低 | 微博短词 vs 知乎长问句：用包含度给出 `related` 候选；但不自动合并 |
| Reddit API 规则 | [reddit-archive/reddit wiki: API](https://github.com/reddit-archive/reddit/wiki/API) | UA 必须是 `<platform>:<app ID>:<version> (by /u/…)` 形式，"NEVER lie about your user-agent"（含伪装浏览器）；需 OAuth2 | Reddit 适配器改用描述性 UA |
| Reddit 匿名 .json 关停 | 二手报道：[DEV Community](https://dev.to/tonywangca/why-reddit-blocked-unauthenticated-json-in-2026-and-how-to-still-get-reddit-data-58b9)、[Crawlora](https://crawlora.net/blog/reddit-json-api-blocked-2026)（均称 2026-05-28 公告、几天内开始 403；未找到 Reddit 原帖） | 匿名 `.json` 返回 403 | 2026-11-02 本机实测 `r/popular/hot.json` 返回 **HTTP 403**，与报道一致；Reddit 保留为可选源但不推荐 |

## 三、本仓库自己的实测（2026-11-02，大陆网络）

| 实测 | 结果 | 结论 |
| --- | --- | --- |
| HN：同一时刻取 Algolia `front_page`（30 条）与 news.ycombinator.com 首页（30 条） | 29 条重合；Algolia 返回顺序是 points 降序，与首页位置的 Spearman ρ = **−0.27**；Algolia 的第 1 名（2765 points）实际在首页第 **25** 位；按简化公式 (points−1)/(T+2)^1.8 用 points 和发帖时间重排，ρ 也只有 0.30（推测与未公开的惩罚项有关） | 估不准，直接读首页 HTML（与 newsnow、DailyHotApi 一致）；Algolia 留作 `--hn-mode algolia` 回退并在 `rank_basis` 写明 |
| 百度 wise 接口 | 第 1 条带 `isTop`（置顶政务条目），页面上没有序号 | 排除出名次，计入 `skipped` |
| 微博 `ajax/statuses/hot_band` | 仍免 cookie 可用；每条带 `realpos`、`onboard_time`（上榜时刻）、`label_name`（新/热/沸/爆）；置顶在单独的 `hotgov` | 保留 `onboard_time` 给 agent 判断时效 |
| 知乎 `api.zhihu.com/topstory/hot-lists/total` | 仍可用，结构未变 | 不改 |
| GitHub Trending | 可达，页面当天只有 15 个仓库，15/15 解析 | 不改 |
| 同源去重 | v0.1.1 把 HN 的 "Who is hiring?" 和 "Who wants to be hired?"（两个不同的月度帖）判成重复（相似度 0.774） | 只做跨源去重 |
| 关键词子串 | 两天真实标题与仓库描述里 "AI" 子串误命中 9 例：Complain、Bonsai、Chairman、Stairs、Training、brain、Awaited 等 | ASCII 缩写改为区分大小写 + 边界 |
| 字符 2-gram 包含度用于英文 | HN↔GitHub 出现 12 对包含度 ≥0.6 的假候选（th/he/in 等太常见） | `related` 只对中文标题计算 |

## 四、本项目的差距与取舍

| 差距 | 处理 |
| --- | --- |
| 没有分享数/搜索量，无法像 BuzzSumo/Google Trends 那样算真实"速度" | 用缓存里的上次名次给出 `rank_delta`（每天 1 次的粗粒度），日报写"上升中"；不冒充速度指标 |
| TrendRadar 支持必须词/过滤词/正则 | 暂不做：当前配置只有关键词列表，agent 可以按语义降级并写理由。若用户反馈误命中多，再加过滤词 |
| 跨语言同事件（中文热搜 vs 英文 HN） | 不做自动判断，交给 agent，宁漏勿错 |
| 微博 `s.weibo.com` 链接需登录才能看全 | 如实标注，不改 |
| 中文源都是无契约接口 | 每源独立降级；本轮复测四个默认源均可用 |
| Reddit 匿名访问已关闭 | 不实现 OAuth（要用户自己申请凭据，超出"零账号"定位），文档标注 403 |

## 附：初版调研（2026-09-19）的需求证据与定位

- 海外付费市场验证了品类：BuzzSumo Content Creation 档 $199/月（[官方定价](https://buzzsumo.com/pricing/)），
  不含 Reddit 与中文平台；AnswerThePublic 约 $20/月，数据源为谷歌补全，对中文选题几乎不可用。
- 中文付费社群的"风向标"类栏目由团队每天人工做多源扫描 → 去口水 → 按会员领域归类 → 推送，
  其中扫描和去重可以脚本化，领域匹配和给角度是 agent 的部分。
- 运营工具普遍把"每天刷各平台找选题要 3-4 小时"作为卖点场景；手工 SOP 基线约每天 30-60 分钟搜集 + 30 分钟汇总。
- 定位：local-first（数据落在本地 JSON 与 markdown，无账号、无 key）；请求克制（每源每次 1 个请求）；
  不越权（只出建议，聚合顺序注明为 AI 建议，热度不跨源换算）。
