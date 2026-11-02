#!/usr/bin/env python3
"""多平台公开热榜抓取与规范化（trend-digest-daily）。

只做确定性的部分：抓取（每源每次 1 个请求）、字段规范化、跨源去重（URL 归一 + 标题相似）、
已见缓存（NEW / 连续在榜 / 名次变化）、跨源名次融合（RRF）、同事件候选（包含度）与领域关键词命中。
跨源聚类命名、选题卡与切入角度由 agent 依 SKILL.md 完成，本脚本不负责。

红线：只用公开接口；每源每次运行最多 1 个 HTTP 请求；不做全站爬取；不循环重试。

用法示例：
  python3 scripts/fetch_trends.py --config config.yaml --output data/trends.json --seen data/seen.jsonl --seen-out data/seen.jsonl
  python3 scripts/fetch_trends.py --offline evals/fixtures/trends_v1 --date 2026-09-19

人类可读摘要一律写 stderr，stdout 只输出 JSON（未指定 --output 时），可直接管道给 jq 等工具。

退出码：0 至少一个源成功；2 参数/IO 错误；3 全部源不可用。
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import html as htmllib
import json
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

VERSION = "0.2.0"
SCHEMA_VERSION = "1.1"  # 1.1：新增 rank_basis/skipped/fusion/related/domain_hits/prev_rank 等字段，旧字段不变

# 源处理与输出的固定顺序（保证同输入输出一致）；前四个为默认启用
CANONICAL_ORDER = ["weibo", "zhihu", "baidu", "hn", "reddit", "github_trending"]
DEFAULT_SOURCES = ["weibo", "zhihu", "baidu", "hn"]

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 各源标题相拟判定的阈值（调研结论：Jaccard 粗筛 + difflib 确认）
JACCARD_MIN = 0.5
DIFFLIB_MIN = 0.6
NEAR_IDENTICAL = 0.9

SEEN_TTL_DAYS = 30

# 跨源名次融合：Reciprocal Rank Fusion（Cormack, Clarke & Büttcher, SIGIR 2009），k=60 为原论文取值。
# 只用源内名次、不碰热度数值，正好绕开"各源热度口径不可比"的问题。
RRF_K = 60

# 同事件候选：短标题字符 2-gram 在长标题中的包含度（Broder 1997 containment）。
# 只作为提示交给 agent 确认，不自动合并（宁漏勿错）；阈值依据见 references/benchmarks.md。
RELATED_CONTAINMENT_MIN = 0.6
RELATED_MIN_CHARS = 4

# Reddit API 规则要求描述性 UA、禁止伪装浏览器（github.com/reddit-archive/reddit/wiki/API）
TOOL_UA = f"python:trend-digest-daily:v{VERSION} (local daily digest script)"


class FetchError(Exception):
    """单源失败（网络/结构/夹具问题），只影响该源，不中断整体运行。"""


# ---------------------------------------------------------------------------
# 源定义：端点、请求头、热度口径说明
# ---------------------------------------------------------------------------

SOURCES: dict[str, dict] = {
    "weibo": {
        "display_name": "微博热搜",
        "endpoint": "https://weibo.com/ajax/statuses/hot_band",
        "headers": {"User-Agent": BROWSER_UA, "Referer": "https://weibo.com/"},
        "hot_value_note": "微博热度值（num），仅源内可比",
    },
    "zhihu": {
        "display_name": "知乎热榜",
        "endpoint": "https://api.zhihu.com/topstory/hot-lists/total?limit=50",
        "headers": {
            "User-Agent": BROWSER_UA,
            "Referer": "https://www.zhihu.com/hot",
        },
        "hot_value_note": "知乎热度（detail_text，如『1590 万热度』换算为数值），仅源内可比",
    },
    "baidu": {
        "display_name": "百度热搜",
        "endpoint": "https://top.baidu.com/api/board?platform=wise&tab=realtime",
        "headers": {
            "User-Agent": BROWSER_UA,
            "Referer": "https://top.baidu.com/board?tab=realtime",
        },
        "hot_value_note": "该端点不返回热度数值，仅源内排名（rank）可比",
    },
    "hn": {
        "display_name": "HN 首页",
        # 默认读首页 HTML 拿真实位置（robots.txt 允许 /，Crawl-delay 30s，每天 1 次远低于此）；
        # --hn-mode algolia 退回 Algolia front_page（按 points 排序，不是首页位置）。
        "endpoint": "https://news.ycombinator.com/",
        "headers": {"User-Agent": TOOL_UA},
        "hot_value_note": "HN points（赞数），仅源内可比",
    },
    "reddit": {
        "display_name": "Reddit 热帖",
        "endpoint": "https://www.reddit.com/r/{sub}/hot.json?limit={limit}&raw_json=1",
        "headers": {"User-Agent": TOOL_UA},
        "hot_value_note": "Reddit score（净赞数），仅源内可比",
    },
    "github_trending": {
        "display_name": "GitHub Trending",
        "endpoint": "https://github.com/trending",
        "headers": {"User-Agent": BROWSER_UA},
        "hot_value_note": "今日新增 star 数，仅源内可比",
    },
}

HN_ALGOLIA_ENDPOINT = "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage={limit}"

# rank 的含义：除 hn algolia 模式外，都是"平台自己展示的榜单位置"，跨源才可以按名次融合
RANK_BASIS = {
    "weibo": "微博热搜榜位置（已跳过 is_ad 广告位）",
    "zhihu": "知乎热榜位置",
    "baidu": "百度热搜榜位置（已跳过 isTop 置顶位，与页面无序号的置顶一致）",
    "hn": "HN 首页实际位置（news.ycombinator.com，已跳过无分数的招聘帖）",
    "hn_algolia": "Algolia front_page 结果顺序＝points 降序，不是首页位置（回退模式）",
    "reddit": "Reddit hot 排序位置（已跳过置顶帖）",
    "github_trending": "GitHub Trending 页面位置",
}


# ---------------------------------------------------------------------------
# 文本与 URL 工具
# ---------------------------------------------------------------------------

def clean_str(value) -> str | None:
    """去掉首尾空白与 HTML 实体，空串归 None。"""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    return text


def clean_topic_title(title: str) -> str:
    """清洗话题外壳：去掉微博话题 # 外壳（保留内部文字）。"""
    text = re.sub(r"^#+|#+$", "", title.strip())
    return text.strip()


def norm_title(title: str) -> str:
    """标题归一（用于相似判定）：去话题外壳、【】、空白与标点，小写。"""
    text = re.sub(r"#([^#]*)#", r"\1", title)
    text = text.replace("【", "").replace("】", "")
    text = re.sub(r"[\W_]+", "", text.lower())
    return text


def title_bigrams(text: str) -> set[str]:
    if len(text) < 2:
        return {text} if text else set()
    return {text[i : i + 2] for i in range(len(text) - 1)}


def title_similarity(a: str, b: str) -> float:
    """标题相似度：字符 2-gram Jaccard 与 difflib 比值取较大者（中文无需分词）。"""
    na, nb = norm_title(a), norm_title(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ga, gb = title_bigrams(na), title_bigrams(nb)
    union = ga | gb
    jaccard = len(ga & gb) / len(union) if union else 0.0
    ratio = difflib.SequenceMatcher(None, na, nb).ratio()
    return max(jaccard, ratio)


def titles_duplicate(a: str, b: str) -> bool:
    """粗筛（Jaccard）后确认（difflib）的调研口径；几乎全等直接判重。"""
    na, nb = norm_title(a), norm_title(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    ga, gb = title_bigrams(na), title_bigrams(nb)
    union = ga | gb
    jaccard = len(ga & gb) / len(union) if union else 0.0
    ratio = difflib.SequenceMatcher(None, na, nb).ratio()
    return ratio >= NEAR_IDENTICAL or (jaccard >= JACCARD_MIN and ratio >= DIFFLIB_MIN)


STRIP_QUERY_PREFIXES = ("utm_", "spm", "from", "fr", "share_", "refer", "scene", "vd_source")


def normalize_url(url: str | None) -> str | None:
    """URL 归一（用于已见缓存 key）：统一 https/去 www、去跟踪参数、折叠知乎问题链接。"""
    if not url or not isinstance(url, str):
        return None
    raw = url.strip()
    if not raw.startswith(("http://", "https://")):
        return None
    parts = urllib.parse.urlsplit(raw)
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parts.path or "/"
    pairs = [
        (k, v)
        for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(STRIP_QUERY_PREFIXES)
    ]
    query = urllib.parse.urlencode(pairs)
    # 知乎：api.zhihu.com/questions/{id} 与 www.zhihu.com/question/{id} 视为同一问题
    match = re.search(r"(?:^|/)questions?/(\d+)", path)
    if netloc.endswith("zhihu.com") and match:
        netloc, path, query = "www.zhihu.com", f"/question/{match.group(1)}", ""
    if path != "/":
        path = path.rstrip("/") or "/"
    normalized = urllib.parse.urlunsplit(("https", netloc, path, query, ""))
    return normalized


def item_key(url: str | None, title: str) -> str:
    normalized = normalize_url(url)
    digest = hashlib.sha1(
        (normalized or "t:" + norm_title(title)).encode("utf-8")
    ).hexdigest()
    return digest[:16]


def num_or_none(value):
    """尽力把接口返回的热度字段转成 int，失败返回 None（不虚构数值）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        match = re.search(r"([\d.]+)\s*万", text)
        if match:
            try:
                return int(float(match.group(1)) * 10000)
            except ValueError:
                return None
        match = re.fullmatch(r"\d+(?:\.\d+)?", text)
        if match:
            return int(float(text))
    return None


# ---------------------------------------------------------------------------
# 抓取上下文：live 走 HTTP（每源至多 1 次），offline 读夹具
# ---------------------------------------------------------------------------

class SourceContext:
    """为单个源提供响应体。负责请求计数，保证每源每次运行至多 1 个请求。"""

    def __init__(self, source: str, limit: int, timeout: float, date_iso: str,
                 offline_dir: Path | None = None, reddit_sub: str = "popular",
                 hn_mode: str = "front"):
        self.source = source
        self.limit = limit
        self.timeout = timeout
        self.date_iso = date_iso
        self.offline_dir = offline_dir
        self.reddit_sub = reddit_sub
        self.hn_mode = hn_mode
        self.skipped: dict[str, int] = {}  # 适配器主动跳过的条目：原因 → 条数（如置顶、广告）
        self.request_count = 0
        self._counter = {"n": 0}

    # -- live --
    def http_get(self, url: str, headers: dict) -> str:
        if self._counter["n"] >= 1:
            raise FetchError("内部错误：单源请求预算已用完（每源每次运行仅 1 个请求）")
        self._counter["n"] += 1
        self.request_count = self._counter["n"]
        request = urllib.request.Request(url, headers=dict(headers), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as error:
            raise FetchError(f"HTTP {error.code}（服务端拒绝或出错，接口可能变动）") from error
        except (urllib.error.URLError, socket.timeout, TimeoutError) as error:
            reason = getattr(error, "reason", error)
            raise FetchError(f"连接失败/超时（{reason}；该源可能需要代理）") from error
        except OSError as error:
            raise FetchError(f"网络错误（{error.__class__.__name__}）") from error

    # -- offline --
    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    def fixture_text(self, source: str, prefer: tuple[str, ...] = (".json", ".html", ".txt")) -> str:
        base = self.offline_dir
        if base is None:
            raise FetchError("内部错误：离线模式未指定夹具目录")
        for name in (f"{source}{ext}" for ext in prefer):
            path = base / name
            if path.is_file():
                try:
                    return path.read_text(encoding="utf-8")
                except OSError as error:
                    raise FetchError(f"夹具读取失败（{error}）") from error
        raise FetchError(f"离线夹具缺失（{base.name}/{source}.json）")

    # -- 统一入口 --
    def body(self, headers: dict, url: str | None = None,
             prefer: tuple[str, ...] = (".json", ".html", ".txt")) -> str:
        if self.offline_dir is not None:
            return self.fixture_text(self.source, prefer)
        definition = SOURCES[self.source]
        target = url or definition["endpoint"].format(limit=self.limit, sub=self.reddit_sub)
        return self.http_get(target, headers)

    def body_json(self, headers: dict, url: str | None = None):
        raw = self.body(headers, url)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as error:
            raise FetchError(f"响应不是合法 JSON（{error.msg}），接口可能改版") from error

    def make_item(self, rank, title, url, hot_value, hot_label=None, extra=None,
                  hot_raw=None) -> dict:
        title = clean_topic_title(title)
        return {
            "source": self.source,
            "rank": rank,
            "title": title,
            "url": url or None,
            "hot_value": hot_value,
            "hot_value_raw": clean_str(str(hot_raw)) if hot_raw is not None else None,
            "hot_label": clean_str(hot_label) if hot_label is not None else None,
            "extra": extra or {},
        }


# ---------------------------------------------------------------------------
# 各源适配器：解析响应体 → 规范化条目（结构变化时抛 FetchError，单源降级）
# ---------------------------------------------------------------------------

def adapt_weibo(ctx: SourceContext) -> list[dict]:
    payload = ctx.body_json(SOURCES["weibo"]["headers"])
    data = payload.get("data") if isinstance(payload, dict) else None
    entries = None
    if isinstance(data, dict):
        for key in ("realtime", "band_list"):
            value = data.get(key)
            if isinstance(value, list) and value:
                entries = value
                break
    if entries is None:
        if isinstance(payload, dict) and payload.get("error"):
            raise FetchError(f"接口拒绝（{payload['error']}，可能需要登录或已风控）")
        raise FetchError("响应结构变化：未找到 realtime/band_list 列表（接口可能改版）")
    items = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("is_ad"):
            ctx.skip("is_ad 广告位")
            continue
        word = clean_str(entry.get("word"))
        if not word:
            continue
        note = clean_str(entry.get("note")) or ""
        title = note if len(clean_topic_title(note)) > len(clean_topic_title(word)) else word
        scheme = entry.get("word_scheme") or f"#{word.strip('#')}#"
        url = "https://s.weibo.com/weibo?q=" + urllib.parse.quote(scheme)
        raw_num = entry.get("num")
        items.append(
            ctx.make_item(
                0, title, url, num_or_none(raw_num),
                entry.get("icon_desc") or entry.get("label_name"),
                {"category": clean_str(entry.get("category")),
                 # 上榜时刻（unix 秒，接口原值），供 agent 判断"刚上榜还是挂了很久"
                 "onboard_time": entry.get("onboard_time")
                 if isinstance(entry.get("onboard_time"), int) else None},
                hot_raw=raw_num,
            )
        )
        if len(items) >= ctx.limit:
            break
    return items


ZHIHU_LABEL_TEXT = {"hot": "热", "new": "新", "recommend": "荐", "discuss": "讨论"}


def adapt_zhihu(ctx: SourceContext) -> list[dict]:
    payload = ctx.body_json(SOURCES["zhihu"]["headers"])
    entries = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        if isinstance(payload, dict) and payload.get("error"):
            raise FetchError(f"接口拒绝（{payload.get('error')}，免签通道可能已收紧）")
        raise FetchError("响应结构变化：未找到 data 列表（接口可能改版）")
    items = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        target = entry.get("target") or {}
        title = clean_str(target.get("title"))
        if not title:
            continue
        raw_url = clean_str(target.get("url")) or ""
        match = re.search(r"questions?/(\d+)", raw_url)
        url = f"https://www.zhihu.com/question/{match.group(1)}" if match else (raw_url or None)
        raw_heat = clean_str(entry.get("detail_text"))
        label = None
        card = entry.get("card_label")
        if isinstance(card, dict):
            label = clean_str(card.get("text")) or ZHIHU_LABEL_TEXT.get(
                clean_str(card.get("type")) or "", clean_str(card.get("type"))
            )
        items.append(
            ctx.make_item(
                0, title, url, num_or_none(raw_heat), label,
                {"answer_count": target.get("answer_count"),
                 "comment_count": target.get("comment_count"),
                 "excerpt": (clean_str(target.get("excerpt")) or "")[:60] or None},
                hot_raw=raw_heat,
            )
        )
        if len(items) >= ctx.limit:
            break
    return items


def adapt_baidu(ctx: SourceContext) -> list[dict]:
    payload = ctx.body_json(SOURCES["baidu"]["headers"])
    if not isinstance(payload, dict):
        raise FetchError("响应不是 JSON 对象（接口可能改版）")
    data = payload.get("data")
    if not isinstance(data, dict):
        detail = payload.get("error") or payload.get("errmsg") or ""
        status = payload.get("status") or payload.get("errno")
        suffix = f"（status={status} {detail}）" if (status or detail) else ""
        raise FetchError(f"响应缺少 data 字段，接口可能改版或服务出错{suffix}")
    found: list[dict] = []

    def walk(node):
        if isinstance(node, dict):
            word = node.get("word")
            if isinstance(word, str) and word.strip():
                found.append(node)
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    items: list[dict] = []
    seen_words: set[str] = set()
    for node in found:
        word = clean_topic_title(node["word"])
        if word in seen_words:
            continue
        if node.get("isTop"):
            # 置顶位在页面上没有序号、不是热度排出来的；与 newsnow 的 baidu 源一致，排除出名次
            seen_words.add(word)
            ctx.skip("isTop 置顶位")
            continue
        seen_words.add(word)
        raw_url = clean_str(node.get("url"))
        url = raw_url or ("https://www.baidu.com/s?wd=" + urllib.parse.quote(word))
        # 实测（2026-09-19）：wise 端点无热度数值；标签在 newHotName（如「热」），
        # hotTag 为数字编码但不公开映射，不猜测，仅在非数字时原样保留。
        label = clean_str(node.get("newHotName"))
        if label is None:
            tag = clean_str(node.get("hotTag"))
            label = tag if tag is not None and not tag.isdigit() else None
        items.append(ctx.make_item(0, word, url, None, label, {}))
        if len(items) >= ctx.limit:
            break
    return items


HN_ROW_RE = re.compile(r'<tr[^>]*class="athing[^"]*"[^>]*id="(\d+)"')


def adapt_hn(ctx: SourceContext) -> list[dict]:
    # 离线夹具兼容：只有 hn.json（Algolia 格式，v0.1.x 夹具）时按 algolia 模式解析；
    # 联网时绝不自动切换（切换就是第 2 个请求，违反每源 1 请求红线）。
    if (ctx.hn_mode == "front" and ctx.offline_dir is not None
            and not (ctx.offline_dir / "hn.html").is_file()
            and (ctx.offline_dir / "hn.json").is_file()):
        ctx.hn_mode = "algolia"
    if ctx.hn_mode == "algolia":
        return adapt_hn_algolia(ctx)
    return adapt_hn_front(ctx)


def adapt_hn_front(ctx: SourceContext) -> list[dict]:
    """解析 news.ycombinator.com 首页：rank 即首页真实位置。

    2026-11-02 实测：Algolia front_page 的返回顺序是 points 降序，与首页位置的 Spearman ρ=-0.27
    （29 条共同条目），"HN#1" 实际在首页第 25 位——所以默认改读首页（与 newsnow/DailyHotApi 一致）。
    """
    page = ctx.body(SOURCES["hn"]["headers"], prefer=(".html",))
    if "athing" not in page:
        raise FetchError("响应里没有 athing 条目（HN 首页结构可能改版，可用 --hn-mode algolia 回退）")
    matches = list(HN_ROW_RE.finditer(page))
    items = []
    for index, match in enumerate(matches):
        story_id = match.group(1)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(page)
        chunk = page[match.start():end]
        link = re.search(r'<span class="titleline"><a href="([^"]+)"[^>]*>(.*?)</a>', chunk, re.DOTALL)
        if not link:
            continue
        title = clean_str(strip_tags(link.group(2)))
        if not title:
            continue
        score = re.search(r'id="score_%s">(\d+)\s*points?' % story_id, chunk)
        if score is None:
            ctx.skip("无分数的招聘帖")  # YC 招聘帖没有投票与分数，属推广位
            continue
        href = htmllib.unescape(link.group(1))
        story_url = f"https://news.ycombinator.com/item?id={story_id}"
        url = href if href.startswith(("http://", "https://")) else story_url
        comments = re.search(r'>(\d+)(?:&nbsp;|\s)comments?</a>', chunk)
        age = re.search(r'<span class="age" title="([0-9T:\-]+)', chunk)
        items.append(
            ctx.make_item(
                0, title, url, int(score.group(1)), None,
                {"num_comments": int(comments.group(1)) if comments else 0,
                 "story_url": story_url,
                 "submitted_at": age.group(1) if age else None},
                hot_raw=score.group(1),
            )
        )
        if len(items) >= ctx.limit:
            break
    return items


def adapt_hn_algolia(ctx: SourceContext) -> list[dict]:
    """回退模式：Algolia front_page（官方 JSON API）。注意 rank 是 points 降序，不是首页位置。"""
    if ctx.offline_dir is not None:
        raw = ctx.fixture_text("hn", (".json",))
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as error:
            raise FetchError(f"响应不是合法 JSON（{error.msg}），接口可能改版") from error
    else:
        payload = ctx.body_json(SOURCES["hn"]["headers"],
                                url=HN_ALGOLIA_ENDPOINT.format(limit=ctx.limit))
    hits = payload.get("hits") if isinstance(payload, dict) else None
    if not isinstance(hits, list):
        raise FetchError("响应结构变化：未找到 hits 列表（接口可能改版）")
    items = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        title = clean_str(hit.get("title"))
        if not title:
            continue
        url = clean_str(hit.get("url"))
        if not url:
            story_id = hit.get("objectID") or hit.get("story_id")
            url = f"https://news.ycombinator.com/item?id={story_id}" if story_id else None
        raw_points = hit.get("points")
        items.append(
            ctx.make_item(
                0, title, url, num_or_none(raw_points), None,
                {"num_comments": num_or_none(hit.get("num_comments")),
                 "story_url": f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
                 if hit.get("objectID") else None},
                hot_raw=raw_points,
            )
        )
        if len(items) >= ctx.limit:
            break
    return items


def adapt_reddit(ctx: SourceContext) -> list[dict]:
    definition = SOURCES["reddit"]
    url = definition["endpoint"].format(limit=min(ctx.limit, 100), sub=ctx.reddit_sub)
    payload = ctx.body_json(definition["headers"], url=url)
    children = (payload.get("data") or {}).get("children") if isinstance(payload, dict) else None
    if not isinstance(children, list):
        raise FetchError("响应结构变化：未找到 data.children 列表（接口可能改版或已限流）")
    items = []
    for child in children:
        data = (child or {}).get("data") or {}
        if data.get("stickied"):
            ctx.skip("stickied 置顶帖")
            continue
        title = clean_str(data.get("title"))
        if not title:
            continue
        permalink = clean_str(data.get("permalink")) or ""
        link = "https://www.reddit.com" + permalink if permalink.startswith("/") else (permalink or None)
        raw_score = data.get("score")
        items.append(
            ctx.make_item(
                0, title, link, num_or_none(raw_score), None,
                {"num_comments": num_or_none(data.get("num_comments"))},
                hot_raw=raw_score,
            )
        )
        if len(items) >= ctx.limit:
            break
    return items


def strip_tags(fragment: str) -> str:
    return htmllib.unescape(re.sub(r"<[^>]+>", "", fragment or "")).strip()


# GitHub 页面中出现在仓库条目附近、但不是仓库链接的保留路径前缀
# （2026-09-19 下午实测：条目内新增 /sponsors/{owner} 赞助按钮、页头有 /sponsors/explore）
GITHUB_NON_REPO_PREFIXES = {
    "features", "collections", "trending", "about", "pricing", "topics", "sponsors",
}


def extract_repo_path(chunk: str) -> str | None:
    """从条目块中取仓库路径：优先 <h2> 标题内的链接（仓库标题），再退回块内首个非保留路径的链接。"""
    heading = re.search(r"<h2[^>]*>(.*?)</h2>", chunk, re.DOTALL)
    if heading:
        match = re.search(r'href="/([\w.-]+/[\w.-]+)"', heading.group(1))
        if match and match.group(1).split("/")[0].lower() not in GITHUB_NON_REPO_PREFIXES:
            return match.group(1)
    for match in re.finditer(r'href="/([\w.-]+/[\w.-]+)"', chunk):
        path = match.group(1)
        if path.split("/")[0].lower() not in GITHUB_NON_REPO_PREFIXES:
            return path
    return None


def adapt_github_trending(ctx: SourceContext) -> list[dict]:
    html = ctx.body(SOURCES["github_trending"]["headers"], prefer=(".html", ".json", ".txt"))
    if "<html" not in html.lower():
        raise FetchError("响应不是 HTML 页面（GitHub Trending 无官方 API，页面可能改版）")
    # 2026-09-19 下午实测：每个仓库改为 <article> 包裹（条目内含 /sponsors/{owner} 赞助按钮）；
    # 兼容旧的 <h2> 布局（无 <article> 时按原逻辑切分）。
    if "<article" in html:
        chunks = html.split("<article")[1:]
    else:
        chunks = html.split("<h2")[1:]
    items = []
    seen_paths: set[str] = set()
    for chunk in chunks:
        path = extract_repo_path(chunk)
        if not path:
            continue
        if path in seen_paths:
            continue
        seen_paths.add(path)
        stars = None
        stars_match = re.search(r"([\d,]+)\s*stars\s*today", chunk)
        if stars_match:
            stars = int(stars_match.group(1).replace(",", ""))
        desc_match = re.search(r'<p class="col-9[^"]*"[^>]*>(.*?)</p>', chunk, re.DOTALL)
        description = strip_tags(desc_match.group(1)) if desc_match else ""
        title = f"{path}：{description}" if description else path
        items.append(
            ctx.make_item(
                0, title, f"https://github.com/{path}", stars, None,
                {"repo": path, "description": description or None},
            )
        )
        if len(items) >= ctx.limit:
            break
    return items


ADAPTERS = {
    "weibo": adapt_weibo,
    "zhihu": adapt_zhihu,
    "baidu": adapt_baidu,
    "hn": adapt_hn,
    "reddit": adapt_reddit,
    "github_trending": adapt_github_trending,
}


# ---------------------------------------------------------------------------
# 已见缓存（seen.jsonl）：NEW 标记 / 连续在榜 streak / 30 天过期
# ---------------------------------------------------------------------------

def load_seen(path: Path | None) -> dict[str, dict]:
    if path is None or not path.is_file():
        return {}
    entries: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and entry.get("key"):
            entries[entry["key"]] = entry
    return entries


def _seen_candidate_ok(item_title: str, entry_title: str) -> bool:
    """廉价预筛：长度差太大的标题 difflib 比值不可能过阈值，跳过以免缓存大时 O(N·M) 变慢。"""
    na, nb = norm_title(item_title), norm_title(entry_title)
    if not na or not nb:
        return False
    shorter, longer = sorted((len(na), len(nb)))
    # difflib ratio ≤ 2·shorter/(shorter+longer)；Jaccard 同理有上界，二者都过不了 DIFFLIB_MIN 就跳过
    return 2 * shorter / (shorter + longer) >= min(DIFFLIB_MIN, JACCARD_MIN)


def match_seen(item: dict, seen_entries: dict[str, dict]):
    """精确 key 命中，否则按标题相似回溯（跨源/跨天的同一事件）。"""
    hit = seen_entries.get(item["key"])
    if hit is not None:
        return hit
    best, best_score = None, 0.0
    for entry in seen_entries.values():
        if not _seen_candidate_ok(item["title"], entry.get("title", "")):
            continue
        score = title_similarity(item["title"], entry.get("title", ""))
        if score > best_score:
            best, best_score = entry, score
    if best is not None and titles_duplicate(item["title"], best.get("title", "")):
        return best
    return None


def seen_status(item: dict, hit: dict | None, today: str) -> dict:
    """由缓存命中结果推出 NEW / 连续在榜 / 名次变化。

    连续在榜（streak）只在"上次出现是昨天"时 +1；同日复跑保持不变；中间断档则重置为 1
    并给出 gap_days（v0.1.x 不论隔多少天都 +1，是 bug）。
    """
    if hit is None:
        return {"is_new": True, "streak": 1, "first_seen": today, "prev_seen": None,
                "prev_rank": None, "rank_delta": None, "gap_days": None}
    last_seen = hit.get("last_seen") or today
    previous_streak = int(hit.get("streak", 1) or 1)
    try:
        gap = (date.fromisoformat(today) - date.fromisoformat(last_seen)).days
    except ValueError:
        gap = None
    if gap == 0:
        streak, gap_days = previous_streak, None
    elif gap == 1:
        streak, gap_days = previous_streak + 1, None
    else:
        streak, gap_days = 1, (gap - 1 if isinstance(gap, int) and gap > 1 else None)
    prev_rank = None
    if hit.get("last_source", hit.get("source")) == item["source"]:
        prev_rank = hit.get("last_rank")
    rank_delta = prev_rank - item["rank"] if isinstance(prev_rank, int) else None
    return {"is_new": False, "streak": streak, "first_seen": hit.get("first_seen", today),
            "prev_seen": hit.get("last_seen"), "prev_rank": prev_rank, "rank_delta": rank_delta, "gap_days": gap_days}


def apply_seen(items: list[dict], seen_entries: dict[str, dict], today: str,
               record_match: bool = True) -> None:
    for item in items:
        hit = match_seen(item, seen_entries)
        if hit is not None and record_match:
            item["matched_seen_key"] = hit["key"]  # 命中旧条目：缓存原地更新，避免重复膨胀
        item.update(seen_status(item, hit, today))


def build_seen_out(items: list[dict], seen_entries: dict[str, dict], today: str) -> dict[str, dict]:
    cutoff = (date.fromisoformat(today) - timedelta(days=SEEN_TTL_DAYS)).isoformat()
    updated = {
        key: entry
        for key, entry in seen_entries.items()
        if entry.get("last_seen", "") >= cutoff
    }
    for item in items:  # 仅收录主条目（dup_of 的重复条目不重复入缓存）
        key = item.get("matched_seen_key") or item["key"]
        previous = updated.get(key)
        updated[key] = {
            "key": key,
            "title": item["title"],
            "source": (previous or item).get("source", item["source"]),
            "first_seen": (previous or item).get("first_seen", today),
            "last_seen": today,
            "best_rank": min(item["rank"], (previous or {}).get("best_rank", item["rank"])),
            "streak": item["streak"],
            "last_source": item["source"],
            "last_rank": item["rank"],
        }
    return dict(sorted(updated.items(), key=lambda pair: pair[0]))


def write_seen(path: Path, entries: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(entry, ensure_ascii=False) for entry in entries.values()]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def fetch_source(source: str, ctx: SourceContext) -> tuple[list[dict], str | None]:
    """抓取单源并赋予 rank；失败返回 ([], 中文原因)。"""
    adapter = ADAPTERS[source]
    try:
        raw_items = adapter(ctx)
    except FetchError as error:
        return [], str(error)
    items = []
    for rank, item in enumerate(raw_items, start=1):
        item["rank"] = rank
        item["key"] = item_key(item["url"], item["title"])
        items.append(item)
    return items, None


def mark_duplicates(source_items: dict[str, list[dict]]) -> None:
    """跨源标题去重：按 CANONICAL_ORDER，先出现者为主条目，后出现者标 dup_of。

    只比较不同源的条目：同一榜单内的条目已由平台去过重，v0.1.x 同源也比较，2026-11-02 实测把
    HN 的「Who is hiring?」和「Who wants to be hired?」两个不同的帖子误并（相似度 0.774）。
    """
    canonical: list[dict] = []
    for source in CANONICAL_ORDER:
        for item in source_items.get(source, []):
            best, best_score = None, 0.0
            for candidate in canonical:
                if candidate["source"] == item["source"]:
                    continue
                score = title_similarity(item["title"], candidate["title"])
                if score > best_score:
                    best, best_score = candidate, score
            if best is not None and titles_duplicate(item["title"], best["title"]):
                item["dup_of"] = best["key"]
                item["dup_of_title"] = best["title"]
                item["dup_similarity"] = round(best_score, 3)
            else:
                item["dup_of"] = None
                canonical.append(item)


CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def count_cjk(text: str) -> int:
    return len(CJK_RE.findall(text))


def title_containment(a: str, b: str) -> float:
    """短标题 2-gram 被长标题包含的比例（Broder 1997 containment）；短标题过短返回 0。"""
    na, nb = norm_title(a), norm_title(b)
    # 只对中文标题计算：英文字符 2-gram（th/he/in…）太常见，2026-11-02 实测 HN↔GitHub 出现
    # 12 对包含度 ≥0.6 的假候选；英文跨源同事件交给 dup_of（Jaccard+difflib）与 agent。
    if min(count_cjk(na), count_cjk(nb)) < RELATED_MIN_CHARS:
        return 0.0
    ga, gb = title_bigrams(na), title_bigrams(nb)
    small, large = (ga, gb) if len(ga) <= len(gb) else (gb, ga)
    return len(small & large) / len(small) if small else 0.0


def mark_related(canonical_items: list[dict]) -> None:
    """标注"可能是同一事件"的跨源候选（不合并，只给 agent 聚类时参考）。

    典型场景：微博短词「郭士强 下课」与知乎长问句「…网友称让郭士强下课，如何评价」，
    Jaccard/difflib 都很低但包含度为 1.0——v0.1.x 完全不提示，全靠 agent 自己发现。
    """
    for item in canonical_items:
        item["related"] = []
    for index, item in enumerate(canonical_items):
        for other in canonical_items[index + 1:]:
            if other["source"] == item["source"]:
                continue
            score = title_containment(item["title"], other["title"])
            if score >= RELATED_CONTAINMENT_MIN:
                rounded = round(score, 3)
                item["related"].append({"key": other["key"], "source": other["source"],
                                        "rank": other["rank"], "containment": rounded})
                other["related"].append({"key": item["key"], "source": item["source"],
                                         "rank": item["rank"], "containment": rounded})


def apply_fusion(all_items: list[dict]) -> None:
    """跨源名次融合（RRF）：主条目 + 指向它的重复条目，按各源最好名次求 Σ 1/(k+rank)。

    只用名次、不碰热度数值；k=60 时上榜源数的影响远大于名次差，正好对应"跨源同发优先"。
    """
    groups: dict[str, list[dict]] = {}
    for item in all_items:
        root = item.get("dup_of") or item["key"]
        groups.setdefault(root, []).append(item)
    for item in all_items:
        if item.get("dup_of"):
            item["fusion"] = None
            continue
        best: dict[str, int] = {}
        for member in groups.get(item["key"], [item]):
            rank = member["rank"]
            if member["source"] not in best or rank < best[member["source"]]:
                best[member["source"]] = rank
        hits = [{"source": src, "rank": best[src]} for src in CANONICAL_ORDER if src in best]
        item["fusion"] = {
            "source_count": len(hits),
            "sources_hit": hits,
            "rrf_score": round(sum(1.0 / (RRF_K + h["rank"]) for h in hits), 6),
        }


# ---------------------------------------------------------------------------
# 领域关键词：只解析 config.yaml 中 domains 的 key/label/keywords（不引第三方 YAML 库）
# ---------------------------------------------------------------------------

class ConfigError(Exception):
    pass


def load_domains(path: Path) -> list[dict]:
    """读取 config.yaml 的 domains 列表。只支持仓库示例的写法：
    `- key: x` / `label: "…"` / `keywords: ["…", "…"]`（行内 JSON 风格列表）。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigError(f"读取失败（{error}）") from error
    domains: list[dict] = []
    in_domains = False
    current: dict | None = None
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if not raw.startswith((" ", "\t", "-")):
            in_domains = raw.split(":", 1)[0].strip() == "domains"
            continue
        if not in_domains:
            continue
        line = raw.strip()
        if line.startswith("- "):
            current = {}
            domains.append(current)
            line = line[2:].strip()
        if current is None:
            continue
        match = re.match(r"(key|label|keywords)\s*:\s*(.*)$", line)
        if not match:
            continue
        field, value = match.group(1), match.group(2).strip()
        if field == "keywords":
            bracket = re.match(r"(\[.*\])", value)
            if not bracket:
                raise ConfigError("keywords 需写成行内列表，如 [\"AI\", \"大模型\"]")
            try:
                words = json.loads(bracket.group(1))
            except json.JSONDecodeError as error:
                raise ConfigError(f"keywords 列表无法解析（{error.msg}）") from error
            current["keywords"] = [w for w in words if isinstance(w, str) and w.strip()]
        else:
            value = re.sub(r"\s+#.*$", "", value).strip().strip('"').strip("'")
            current[field] = value
    result = [d for d in domains if d.get("key") and d.get("keywords")]
    if not result:
        raise ConfigError("没有找到含 key 与 keywords 的 domains 条目")
    for domain in result:
        domain.setdefault("label", domain["key"])
    return result


def keyword_matches(keyword: str, title: str) -> bool:
    """关键词命中规则（v0.2.0）。

    - 含中文等非 ASCII 字符：子串匹配（中文无空格分词，与 TrendRadar 一致）。
    - 全大写 ASCII 缩写（AI/GPT）：区分大小写，前面不能是大写字母/数字、后面不能接字母数字
      （复数 s 除外）→ 命中 OpenAI / ChatGPT / xAI，不命中 "Complain"、"Bonsai"；
      另外允许两侧都是非字母数字时不区分大小写（如中文里的「ai绘画」）。
    - 其他 ASCII 词（Agent/Claude）：不区分大小写，只要求左边界 → 命中 Agents / Agentic。
    依据：2026-11-02 与 2026-09-19 真实标题中 "AI" 子串误命中 9 例（见 evals/iteration_notes.md）。
    """
    kw = keyword.strip()
    if not kw:
        return False
    if not kw.isascii():
        return kw.lower() in title.lower()
    escaped = re.escape(kw)
    if re.fullmatch(r"[A-Z0-9]+", kw) and re.search(r"[A-Z]", kw):
        if re.search(r"(?<![A-Z0-9])" + escaped + r"(?:s)?(?![A-Za-z0-9])", title):
            return True
        return bool(re.search(r"(?<![A-Za-z0-9])" + escaped + r"(?![A-Za-z0-9])", title, re.I))
    return bool(re.search(r"(?<![A-Za-z0-9])" + escaped, title, re.I))


def apply_domains(items: list[dict], domains: list[dict]) -> None:
    for item in items:
        text = item["title"]
        description = (item.get("extra") or {}).get("description")
        if description and description not in text:
            text = f"{text} {description}"
        hits = []
        for domain in domains:
            matched = [kw for kw in domain["keywords"] if keyword_matches(kw, text)]
            if matched:
                hits.append({"key": domain["key"], "label": domain["label"], "matched": matched})
        item["domain_hits"] = hits


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fetch_trends.py",
        description="多平台公开热榜抓取与规范化（每源每次 1 个请求）",
    )
    parser.add_argument("--sources", default=",".join(DEFAULT_SOURCES),
                        help=f"逗号分隔的源列表（默认 {','.join(DEFAULT_SOURCES)}；可选 {'/'.join(['reddit','github_trending'])}）")
    parser.add_argument("--limit", type=int, default=30, help="每源最多保留条数（默认 30）")
    parser.add_argument("--timeout", type=float, default=10.0, help="单源超时秒数（默认 10）")
    parser.add_argument("--date", default=None, help="数据日期 ISO 格式（默认今天；评测时固定）")
    parser.add_argument("--offline", default=None, metavar="DIR",
                        help="离线夹具目录（读取 DIR/{source}.json|.html，不联网）")
    parser.add_argument("--reddit-sub", default="popular", help="Reddit 版名（默认 popular）")
    parser.add_argument("--hn-mode", choices=["front", "algolia"], default="front",
                        help="HN 取数方式：front=首页真实位置（默认）；algolia=Algolia front_page（points 排序）")
    parser.add_argument("--config", default=None, metavar="FILE",
                        help="博主领域配置（config.yaml）；给出后每条输出 domain_hits 关键词命中")
    parser.add_argument("--seen", default=None, metavar="FILE",
                        help="已见缓存 JSONL（只读，用于 NEW/streak 判定）")
    parser.add_argument("--seen-out", default=None, metavar="FILE",
                        help="更新后的已见缓存输出路径（可与 --seen 相同）")
    parser.add_argument("--output", default=None, help="规范化 JSON 输出路径（默认 stdout）")
    parser.add_argument("--quiet", action="store_true", help="不向 stderr 打印人类可读摘要")
    args = parser.parse_args(argv)
    if args.limit < 1:
        print("错误：--limit 必须 ≥1", file=sys.stderr)
        return 2

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    if not sources:
        print(f"错误：--sources 为空（可用：{','.join(CANONICAL_ORDER)}）", file=sys.stderr)
        return 2
    unknown = [s for s in sources if s not in ADAPTERS]
    if unknown:
        print(f"错误：未知源 {','.join(unknown)}（可用：{','.join(CANONICAL_ORDER)}）", file=sys.stderr)
        return 2
    sources.sort(key=CANONICAL_ORDER.index)

    try:
        today = args.date or date.today().isoformat()
        date.fromisoformat(today)
    except ValueError:
        print(f"错误：--date 不是合法 ISO 日期：{args.date}", file=sys.stderr)
        return 2

    offline_dir = Path(args.offline) if args.offline else None
    if offline_dir is not None and not offline_dir.is_dir():
        print(f"错误：离线夹具目录不存在：{offline_dir}", file=sys.stderr)
        return 2
    seen_path = Path(args.seen) if args.seen else None
    seen_entries = load_seen(seen_path)

    domains: list[dict] | None = None
    domain_note = "未提供 --config，未做领域匹配（agent 输出通用版）"
    if args.config:
        try:
            domains = load_domains(Path(args.config))
            domain_note = f"已按 {Path(args.config).name} 的 {len(domains)} 个领域做关键词命中"
        except ConfigError as error:
            domain_note = f"配置无法解析，已跳过领域匹配：{error}"
            print(f"警告：{args.config} {domain_note}", file=sys.stderr)

    source_blocks = []
    all_items: list[dict] = []
    for source in sources:
        ctx = SourceContext(source, limit=args.limit, timeout=args.timeout,
                            date_iso=today, offline_dir=offline_dir,
                            reddit_sub=args.reddit_sub, hn_mode=args.hn_mode)
        items, error = fetch_source(source, ctx)
        all_items.extend(items)
        definition = SOURCES[source]
        algolia = source == "hn" and ctx.hn_mode == "algolia"
        source_blocks.append({
            "source": source,
            "display_name": definition["display_name"],
            "endpoint": HN_ALGOLIA_ENDPOINT.split("?")[0] if algolia else definition["endpoint"],
            "status": "ok" if error is None else "unavailable",
            "error": error,
            "requests": ctx.request_count,
            "rank_basis": RANK_BASIS["hn_algolia" if algolia else source],
            "hot_value_note": definition["hot_value_note"],
            "skipped": dict(sorted(ctx.skipped.items())),
            "item_count": len(items),
            "items": items,
        })

    mark_duplicates(
        {block["source"]: block["items"] for block in source_blocks}
    )
    canonical_items = [i for i in all_items if not i.get("dup_of")]
    apply_seen(canonical_items, seen_entries, today)
    # 重复条目也带 NEW/streak 供参考（与主条目同一套规则，但不写缓存）
    apply_seen([i for i in all_items if i.get("dup_of")], seen_entries, today, record_match=False)
    apply_fusion(all_items)
    mark_related(canonical_items)
    if domains is not None:
        apply_domains(all_items, domains)

    if args.seen_out:
        try:
            write_seen(Path(args.seen_out), build_seen_out(canonical_items, seen_entries, today))
        except OSError as error:
            print(f"错误：已见缓存写入失败（{error}）", file=sys.stderr)
            return 2

    new_count = sum(1 for item in canonical_items if item["is_new"])
    duplicate_count = sum(1 for item in all_items if item.get("dup_of"))
    ok_sources = sum(1 for block in source_blocks if block["status"] == "ok")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "tool": "fetch_trends.py",
        "tool_version": VERSION,
        "fetched_date": today,
        "mode": "offline" if offline_dir is not None else "live",
        "sources_enabled": sources,
        "notes": {
            "hot_value_comparability": "各源热度口径不同，hot_value 仅在源内可比；跨源比较请用源内排名",
            "aggregation": "dup_of 为跨源标题重复标记；聚类命名与选题建议由 agent 依 SKILL.md 生成",
            "red_line": "只用公开接口，每源每次运行 1 个请求，不做全站爬取",
            "fusion": f"fusion.rrf_score = Σ 1/({RRF_K}+源内名次)（RRF，Cormack 2009），只用名次不用热度；"
                      "是排序参考而非官方排名",
            "related": f"related 为包含度 ≥{RELATED_CONTAINMENT_MIN} 的跨源同事件候选，脚本不合并，由 agent 确认",
            "streak": "streak 只在上次出现为昨天时 +1，断档重置为 1 并给 gap_days；rank_delta=上次名次-今日名次（正数=上升）",
            "domain_matching": domain_note,
        },
        "summary": {
            "total_items": len(all_items),
            "unique_items": len(canonical_items),
            "duplicate_items": duplicate_count,
            "new_items": new_count,
            "multi_source_topics": sum(
                1 for item in canonical_items if (item.get("fusion") or {}).get("source_count", 0) >= 2),
            "related_pairs": sum(len(item.get("related", [])) for item in canonical_items) // 2,
            "sources_ok": ok_sources,
            "sources_unavailable": len(source_blocks) - ok_sources,
        },
        "sources": source_blocks,
    }

    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        try:
            out_path = Path(args.output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(rendered, encoding="utf-8")
        except OSError as error:
            print(f"错误：输出写入失败（{error}）", file=sys.stderr)
            return 2
    else:
        sys.stdout.write(rendered)

    if not args.quiet:
        # 摘要只写 stderr：v0.1.x 写 stdout，未指定 --output 时会把 JSON 弄坏
        for block in source_blocks:
            name = block["display_name"]
            if block["status"] == "ok":
                fresh = sum(1 for item in block["items"] if not item.get("dup_of") and item.get("is_new"))
                skipped = sum(block["skipped"].values())
                tail = f"，跳过 {skipped} 条非自然位" if skipped else ""
                print(f"[{name}] 成功 · {block['item_count']} 条（NEW {fresh}{tail}）", file=sys.stderr)
            else:
                print(f"[{name}] 源不可用：{block['error']}（已跳过，不影响其他源）", file=sys.stderr)
        multi = sum(1 for item in canonical_items if (item.get("fusion") or {}).get("source_count", 0) >= 2)
        related_pairs = sum(len(item.get("related", [])) for item in canonical_items) // 2
        target = args.output or "stdout"
        print(
            f"共 {len(all_items)} 条 → 去重后 {len(canonical_items)} 条"
            f"（跨源重复 {duplicate_count}，跨源同发话题 {multi}，同事件候选 {related_pairs} 对，"
            f"NEW {new_count}）；JSON 已写入 {target}",
            file=sys.stderr,
        )

    return 0 if ok_sources >= 1 else 3


if __name__ == "__main__":
    raise SystemExit(run())
