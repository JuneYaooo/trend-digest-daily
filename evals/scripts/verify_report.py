#!/usr/bin/env python3
"""回核日报（t17）：报告里的链接、「源#名次」与热度数字必须都能在当日 JSON 里找到。

用法：python3 evals/scripts/verify_report.py REPORT.md TRENDS.json [--output RESULT.json]
检查项：
  1. 每个 http(s) 链接都等于 JSON 中某条目的 url（防编造链接）；
  2. 每处「微博#N / 知乎#N / 百度#N / HN 首页#N」都对应该源存在的名次；
  3. 「知乎#N（…X 万热度）」「HN 首页#N（X points）」「微博#N（…X 万热度）」的数字与该条目 hot_value 一致；
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SOURCE_NAMES = {"微博": "weibo", "知乎": "zhihu", "百度": "baidu", "HN 首页": "hn", "HN": "hn",
                "GitHub Trending": "github_trending"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report")
    parser.add_argument("trends")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    report = Path(args.report).read_text(encoding="utf-8")
    data = json.loads(Path(args.trends).read_text(encoding="utf-8"))
    by_rank = {(b["source"], i["rank"]): i for b in data["sources"] for i in b["items"]}
    urls = {i["url"] for i in by_rank.values() if i.get("url")}

    problems: list[str] = []
    links = re.findall(r"\]\((https?://[^)\s]+)\)", report)
    for url in links:
        if url not in urls:
            problems.append(f"链接不在 JSON 中：{url}")

    refs = list(re.finditer(r"(HN 首页|微博|知乎|百度|GitHub Trending)#(\d+)(（[^）]*）)?", report))
    for match in refs:
        source = SOURCE_NAMES[match.group(1)]
        rank = int(match.group(2))
        item = by_rank.get((source, rank))
        if item is None:
            problems.append(f"名次不存在：{match.group(0)}")
            continue
        detail = match.group(3) or ""
        wan = re.search(r"([\d.]+)\s*万热度", detail)
        if wan and source in ("zhihu", "weibo"):
            value = float(wan.group(1)) * 10000
            if item["hot_value"] is None or abs(item["hot_value"] - value) > 10000 * 0.051:
                problems.append(f"热度不符：{match.group(0)}（JSON={item['hot_value']}）")
        points = re.search(r"(\d+) points", detail)
        if points and source == "hn" and int(points.group(1)) != item["hot_value"]:
            problems.append(f"points 不符：{match.group(0)}（JSON={item['hot_value']}）")

    result = {
        "report": args.report,
        "trends": args.trends,
        "links_checked": len(links),
        "rank_refs_checked": len(refs),
        "problems": problems,
        "passed": not problems,
    }
    if args.output:
        Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
