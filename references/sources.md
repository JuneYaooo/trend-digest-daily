# 数据源接口说明（2026-09-19 实测，2026-11-02 复测）

各源均为**公开/半公开端点，无任何鉴权与稳定性承诺**，字段随时可能改版——脚本的每源独立降级
就是为此设计。本文件记录 2026-09-19（中国大陆网络、macOS）两次实测与 2026-11-02 复测
可用的端点、解析字段与已知风险。接口行为的最终解释权属于各平台。

每源输出都带 `rank_basis`（名次含义）与 `skipped`（被排除的置顶/广告位条数）。除 HN 的 algolia
回退模式外，rank 都是**平台自己展示的榜单位置**，所以跨源可以按名次融合（RRF），热度数值则不行。

## 默认启用（大陆网络直连可用）

### 微博热搜（weibo）

- 端点：`GET https://weibo.com/ajax/statuses/hot_band`，请求头须带浏览器
  `User-Agent` + `Referer: https://weibo.com/`（实测免 cookie）。
- 解析字段：`data.realtime[]`（兼容 `band_list[]`）的 `word / note / num / word_scheme /
  icon_desc / label_name / is_ad`；`is_ad=1` 跳过；话题 `#` 外壳清洗；条目链接由
  `word_scheme` 构造为 `https://s.weibo.com/weibo?q=…`；`onboard_time`（上榜时刻，unix 秒）放进
  `extra.onboard_time`。2026-11-02 复测：列表键为 `band_list`（50 条），另有 `hotgov` 置顶政务条目，
  脚本不读 `hotgov`；`label_name` 取值有 新/热/沸/爆。
- 热度口径：`num`（微博热度值），仅源内可比。
- 风险：备用端点 `ajax/side/hotSearch` 实测无 cookie 返回 `{"error":"Forbidden"}`（已拒匿名）；
  `s.weibo.com` 搜索页需登录才能看完整内容；建议频率 ≤1 次/小时。

### 知乎热榜（zhihu）

- 端点：`GET https://api.zhihu.com/topstory/hot-lists/total?limit=50`（老版 App 接口，实测免签名）。
- 解析字段：`data[].target.title / url / answer_count / follower_count / excerpt`、
  `data[].detail_text`（如「1574 万热度」，脚本换算为数值）、`data[].card_label.type`
  （映射 hot→热 / new→新 / recommend→荐 / discuss→讨论）；链接改写为
  `https://www.zhihu.com/question/{id}`。
- 热度口径：`detail_text` 数值，仅源内可比。
- 风险：新版 v3 端点需 `x-zse-96` 签名，本仓库**不实现**签名算法；老接口无承诺，随时可能收紧，
  失效时按"源不可用"降级。

### 百度热搜（baidu）

- 端点：`GET https://top.baidu.com/api/board?platform=wise&tab=realtime`（带浏览器 UA）。
- 解析字段：`data.cards[].content[].content[]` 嵌套中的 `word / url / newHotName / hotTag / isTop`
  （脚本对结构做递归查找，兼容层级变化）；`url` 为百度搜索跳链而非原文。
  `isTop` 置顶位（2026-11-02 实测为第 1 条，页面上无序号）**不计入名次**，计入 `skipped`
  ——与 newsnow 的 baidu 源做法一致。
- 热度口径：**该端点不返回热度数值**，仅源内排名可比；PC 网页版 HTML 内嵌 `hotScore`
  但属页面结构，随时会变，脚本不解析。
- 风险：错误体形如 `{"status":500,"data":null}`，脚本按"响应缺少 data 字段"降级；
  条目去重按 `word` 而非 URL（跳链 url 各不相同，同一词会重复出现）。

### Hacker News 首页（hn）

- 默认端点（v0.2.0 起）：`GET https://news.ycombinator.com/`（首页 HTML）。robots.txt 允许 `/`，
  `Crawl-delay: 30`，每天 1 次远低于限制；UA 为描述性的 `python:trend-digest-daily:vX.Y.Z (…)`。
- 解析：每个 `<tr class="athing submission" id=…>` 为一条；标题与链接取 `.titleline` 内第一个 `<a>`
  （站内帖回退为 `item?id=`），`score_{id}` 为 points，`N comments` 为评论数，`.age` 的 `title`
  为发帖时间。**没有分数的行是 YC 招聘帖，跳过并计入 `skipped`**。rank = 首页真实位置。
- 回退：`--hn-mode algolia` 用 `GET https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage={limit}`
  （官方 JSON API）。注意它按 points 降序返回，**不是首页顺序**：2026-11-02 同一时刻对比，29 条共同
  条目与首页位置的 Spearman ρ=−0.27，Algolia 第 1 名在首页第 25 位。`rank_basis` 会写明。
  联网时两种模式只发 1 个请求，绝不自动切换；离线夹具只有 `hn.json` 时按 algolia 解析（兼容 v0.1 夹具）。
- 热度口径：`points`（赞数），仅源内可比。
- 风险：首页 HTML 改版即降级（newsnow/DailyHotApi 同样依赖它）。Firebase 官方 API 需要逐条取 item
  （多请求），违反每源 1 请求红线，不采用。

## 可选源（`--sources` 手动启用）

### Reddit 热帖（reddit）

- 端点：`GET https://www.reddit.com/r/{sub}/hot.json?limit={limit}&raw_json=1`
  （`--reddit-sub` 指定版名，默认 popular；每源每次仍只请求 1 个版）。
- 解析字段：`data.children[].data.title / permalink / score / num_comments / stickied`
  （置顶跳过）。
- 热度口径：`score`（净赞数），仅源内可比。
- 现状：**基本不可用**。据多篇二手报道，Reddit 于 2026-05-28 宣布关闭匿名 `.json` 访问，几天内开始返回
  403（未找到 Reddit 原帖，见 references/benchmarks.md）；2026-11-02 本机实测 `r/popular/hot.json` 返回
  HTTP 403（09-19 两次为超时）。Reddit API 规则要求描述性 UA、禁止伪装浏览器，v0.2.0 已改用
  `python:trend-digest-daily:vX.Y.Z (…)`。官方通道是 OAuth2，需用户自行申请凭据，与本项目"零账号"定位
  冲突，未实现。失败即跳过不重试。

### GitHub Trending（github_trending）

- 端点：`GET https://github.com/trending`（无官方 API，解析 HTML）。
- 解析字段（2026-09-19 第二次联网回归后更新）：每个仓库一个 `<article>` 块，取 `<h2>` 标题内
  `href="/{owner}/{repo}"`、`<p class="col-9…">` 描述、`N stars today` 数值；兼容旧的纯 `<h2>` 布局。
  条目内可能带 `/sponsors/{owner}` 赞助按钮、页面带 `/sponsors/explore` 链接，均按保留路径前缀
  （features/collections/trending/about/pricing/topics/sponsors）排除，不当成仓库。
- 热度口径：今日新增 star 数，仅源内可比。
- 风险：HTML 结构改版即失效（宽松正则 + 失效降级）。直连可用性随网络环境波动：建仓时（当日凌晨）
  实测超时，同日下午第二次回归实测直连可达并解析 17/17 个仓库——期间页面已发生一次结构变化
  （赞助按钮链接插入条目），旧适配器把 `/sponsors/explore` 误当条目，已修复并加回归测试
  （见 evals/iteration_notes.md 迭代 4）。2026-11-02 复测可达，页面当天 15 个仓库，15/15 解析；
  描述中的 HTML 实体（`&amp;` 等）v0.2.0 起解码。

## 通用约束

- 每源每次运行至多 1 个 HTTP 请求，脚本内 `SourceContext.http_get` 有请求预算硬限制（第二次调用直接抛错）；
  单源超时默认 10s，可 `--timeout` 调整但禁止用重试换成功率。
- 只取标题、公开热度数与链接，不转载正文；日报引用须附原帖链接。
