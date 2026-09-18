# 数据源接口说明（2026-09-19 实测）

各源均为**公开/半公开端点，无任何鉴权与稳定性承诺**，字段随时可能改版——脚本的每源独立降级
就是为此设计。本文件记录建仓当日（2026-09-19，中国大陆网络、macOS）实测可用的端点、
解析字段与已知风险。接口行为的最终解释权属于各平台。

## 默认启用（大陆网络直连可用）

### 微博热搜（weibo）

- 端点：`GET https://weibo.com/ajax/statuses/hot_band`，请求头须带浏览器
  `User-Agent` + `Referer: https://weibo.com/`（实测免 cookie）。
- 解析字段：`data.realtime[]`（兼容 `band_list[]`）的 `word / note / num / word_scheme /
  icon_desc / label_name / is_ad`；`is_ad=1` 跳过；话题 `#` 外壳清洗；条目链接由
  `word_scheme` 构造为 `https://s.weibo.com/weibo?q=…`。
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
- 热度口径：**该端点不返回热度数值**，仅源内排名可比；PC 网页版 HTML 内嵌 `hotScore`
  但属页面结构，随时会变，脚本不解析。
- 风险：错误体形如 `{"status":500,"data":null}`，脚本按"响应缺少 data 字段"降级；
  条目去重按 `word` 而非 URL（跳链 url 各不相同，同一词会重复出现）。

### Hacker News 首页（hn）

- 端点：`GET https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage={limit}`
  （官方 API，免鉴权，文档 https://hn.algolia.com/api）。
- 解析字段：`hits[].title / url / points / num_comments / objectID`；`url` 为空时回退
  `https://news.ycombinator.com/item?id={objectID}`。
- 热度口径：`points`（赞数），仅源内可比。
- 风险：最低；官方公开 API。备选 Firebase 端点 `hacker-news.firebaseio.com/v0/topstories.json`
  需逐条取 item（多请求），违反每源 1 请求红线，不采用。

## 可选源（需代理，`--sources` 手动启用）

### Reddit 热帖（reddit）

- 端点：`GET https://www.reddit.com/r/{sub}/hot.json?limit={limit}&raw_json=1`
  （`--reddit-sub` 指定版名，默认 popular；每源每次仍只请求 1 个版）。
- 解析字段：`data.children[].data.title / permalink / score / num_comments / stickied`
  （置顶跳过）。
- 热度口径：`score`（净赞数），仅源内可比。
- 风险：匿名额度约 10 req/min/IP 且对数据中心 IP 常见 403/429，官方对非 OAuth 流量持续收紧；
  大陆网络直连超时（2026-09-19 实测）。失败即跳过不重试。

### GitHub Trending（github_trending）

- 端点：`GET https://github.com/trending`（无官方 API，解析 HTML）。
- 解析字段：`<h2>` 内 `href="/{owner}/{repo}"`、`<p class="col-9…">` 描述、
  `N stars today` 数值。
- 热度口径：今日新增 star 数，仅源内可比。
- 风险：HTML class 改名即失效（宽松正则 + 失效降级）；大陆网络直连 github.com 超时
  （2026-09-19 实测，api.github.com 可达）。

## 通用约束

- 每源每次运行至多 1 个 HTTP 请求，脚本内 `SourceContext.http_get` 有请求预算硬限制（第二次调用直接抛错）；
  单源超时默认 10s，可 `--timeout` 调整但禁止用重试换成功率。
- 只取标题、公开热度数与链接，不转载正文；日报引用须附原帖链接。
