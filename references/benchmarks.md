# 对标：同类工具与本项目定位（2026-09-19 调研）

调研方法：公开网页与 GitHub 仓库阅读，star 数为 2026-09-19 经 api.github.com 查询的数值；
引用版权归原作者所有，仅作定位说明，本仓库未转载任何第三方代码或内容。

## 需求证据

- 海外付费市场验证了品类：BuzzSumo Content Creation 档 **$199/月（年付，单人）**
  （[官方定价](https://buzzsumo.com/pricing/)、[Capterra 页面](https://www.capterra.com/p/139886/BuzzSumo/)），
  Trending Feeds 以"增速"排序；但社交互动数据以 Facebook/X/Pinterest 为主，
  **不含 Reddit、不含任何中文平台**。AnswerThePublic 约 $20/月、免费档每天仅 3 次搜索，
  数据源为谷歌补全，对中文选题几乎不可用。
- 中文付费社群的"风向标"类栏目由团队**每天人工**做多源扫描→去口水→按会员领域归类→每日推送
  （生财有术等），证明"每日情报帖"形态有人按年付费——其中①扫描②去重完全可脚本化，
  ③领域匹配④给角度正是 agent 部分。
- 运营工具普遍把"每天刷各平台找选题要 3-4 小时"作为卖点场景；手工 SOP 基线约
  "每天 30-60 分钟搜集 + 30 分钟汇总进选题表"。

## 现有开源方案与差距

| 项目 | Star | 做法 | 与本项目的差异 |
| --- | --- | --- | --- |
| [newsnext/newsnow](https://github.com/newsnext/newsnow) | 21,746 | TypeScript，40+ 源实时聚合阅读器，需 Cloudflare/Docker 常驻部署 | 是"阅读器"不是"编辑器"：不去重聚类、无领域匹配、不产选题建议 |
| [DIYgod/RSSHub](https://github.com/DIYgod/RSSHub) | 46,241 | 万能 RSS 生成器，部分中文路由需 cookie | 只负责"把热点变成 RSS"，后续全部自己来；Node 生态非纯标准库 |
| [imsyy/DailyHotApi](https://github.com/imsyy/DailyHotApi) | 4,063 | 聚合 60+ 平台热榜，JSON/RSS 输出，Vercel/Docker 部署 | 国内路由随上游改版经常失效；同样止步于"聚合展示" |
| [bonfy/github-trending](https://github.com/bonfy/github-trending) 等存档类 | 1,152 / 396 / 58 | 单源每日存档 | 纯存档，无分析 |
| [Pangu-Immortal/hunter-ai-content-factory](https://github.com/Pangu-Immortal/hunter-ai-content-factory) | 394 | 热点采集→AI 判断→生成文章→自动发布 | 终点是自动发文而非"给人看的选题卡"；依赖难获取源；中文源缺失 |
| 小红书/多平台选题类 Agent Skill（12-140★） | <200 | 绑定单一平台 | 无"local-first + 纯标准库 + 多源去重缓存"基础层 |

**结论**：全网"聚合"层开源很多，但"聚合 → 去重聚类 → 与个人领域匹配 → 每日选题卡"的
最后一公里没有 local-first 的开源实现。本仓库自建轻量抓取（每源 1 请求/天），
换取零依赖、零常驻服务、单文件可审计。

## 本项目立场

- local-first：数据落在本地 JSON 与 markdown，无账号、无 key、无上传。
- 请求克制：每源每次 1 个请求，不做全站爬取；源挂了如实标注而不是换姿势硬抓。
- 不越权：只出"建议"，聚合顺序注明为 AI 建议；热度不做跨源换算，发布判断留给人。
