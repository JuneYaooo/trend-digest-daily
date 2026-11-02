#!/usr/bin/env python3
"""v0.1.1 vs v0.2.0 同输入对比（t16）。

输入：一份冻结的真实原始响应目录（每源 1 个文件，2026-11-02 联网各取 1 次），
旧版读 hn.json（Algolia），新版读 hn.html（首页）——两个文件是同一时刻各 1 次请求的结果。
原始响应含第三方正文摘要与用户名，不入库；本脚本只把对比指标与条目标题级摘要写进
evals/runs_v2/before_after_2026-11-02.json，并记录每个原始文件的 sha256 以便核对。

用法：
  python3 evals/scripts/compare_versions.py --raw DIR [--old-script PATH] [--old-commit 4c26a28]
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import io
import itertools
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCES = "weibo,zhihu,baidu,hn,github_trending"
DAY = "2026-11-02"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_quiet(module, argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = module.run(argv)
    return code, out.getvalue(), err.getvalue()


def spearman(order_a: list[str], order_b: list[str]) -> tuple[int, float | None]:
    common = [x for x in order_a if x in set(order_b)]
    n = len(common)
    if n < 2:
        return n, None
    ra = {x: i for i, x in enumerate(common)}
    rb = {x: i for i, x in enumerate(sorted(common, key=order_b.index))}
    d2 = sum((ra[x] - rb[x]) ** 2 for x in common)
    return n, round(1 - 6 * d2 / (n * (n * n - 1)), 3)


def naive_hits(keywords: list[str], title: str) -> list[str]:
    """v0.1.x 的口径：report-format 只写"命中关键词"，agent 实际按不区分大小写子串判断。"""
    return [k for k in keywords if k.lower() in title.lower()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", required=True, help="冻结的原始响应目录（weibo/zhihu/baidu.json、hn.json、hn.html、github_trending.html）")
    parser.add_argument("--old-script", default=None, help="v0.1.1 的 fetch_trends.py；缺省从 git 提交取")
    parser.add_argument("--old-commit", default="4c26a28")
    parser.add_argument("--output", default=str(REPO_ROOT / f"evals/runs_v2/before_after_{DAY}.json"))
    args = parser.parse_args()
    raw = Path(args.raw)

    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        if args.old_script:
            old_path = Path(args.old_script)
        else:
            old_path = tmp / "fetch_trends_old.py"
            old_path.write_text(subprocess.check_output(
                ["git", "-C", str(REPO_ROOT), "show", f"{args.old_commit}:scripts/fetch_trends.py"],
                text=True), encoding="utf-8")
        old = load_module(old_path, "ft_old")
        new = load_module(REPO_ROOT / "scripts/fetch_trends.py", "ft_new")

        # 旧版只认 {source}.json 优先，给它一个不含 hn.html 的目录
        old_raw = tmp / "raw_old"
        old_raw.mkdir()
        for f in raw.iterdir():
            if f.name != "hn.html":
                (old_raw / f.name).write_bytes(f.read_bytes())

        old_out, new_out = tmp / "old.json", tmp / "new.json"
        old_seen, new_seen = tmp / "old_seen.jsonl", tmp / "new_seen.jsonl"
        run_quiet(old, ["--offline", str(old_raw), "--sources", SOURCES, "--date", DAY,
                        "--output", str(old_out), "--seen-out", str(old_seen), "--quiet"])
        run_quiet(new, ["--offline", str(raw), "--sources", SOURCES, "--date", DAY,
                        "--config", str(REPO_ROOT / "config.yaml"),
                        "--output", str(new_out), "--seen-out", str(new_seen), "--quiet"])
        o, n = json.loads(old_out.read_text()), json.loads(new_out.read_text())
        ob = {b["source"]: b for b in o["sources"]}
        nb = {b["source"]: b for b in n["sources"]}

        # 1) HN：rank 与首页真实位置的一致性
        front_ids = re.findall(r'class="athing[^"]*"[^>]*id="(\d+)"', (raw / "hn.html").read_text())
        def hn_ids(block):
            ids = []
            for item in block["items"]:
                story = (item["extra"] or {}).get("story_url") or item["url"] or ""
                match = re.search(r"id=(\d+)", story)
                ids.append(match.group(1) if match else None)
            return [i for i in ids if i]
        old_hn_ids, new_hn_ids = hn_ids(ob["hn"]), hn_ids(nb["hn"])
        old_top = ob["hn"]["items"][0]
        hn_cmp = {
            "front_page_ids": len(front_ids),
            "old_spearman_vs_front": spearman(old_hn_ids, front_ids),
            "new_spearman_vs_front": spearman(new_hn_ids, front_ids),
            "old_rank1": {"title": old_top["title"], "points": old_top["hot_value"],
                          "actual_front_position": front_ids.index(old_hn_ids[0]) + 1 if old_hn_ids[0] in front_ids else None},
            "new_rank1": {"title": nb["hn"]["items"][0]["title"], "points": nb["hn"]["items"][0]["hot_value"]},
        }

        # 2) 去重：同源误并
        def same_source_dups(block_map):
            out = []
            for block in block_map.values():
                keys = {i["key"]: i["title"] for i in block["items"]}
                for item in block["items"]:
                    if item.get("dup_of") in keys:
                        out.append({"source": block["source"], "title": item["title"],
                                    "merged_into": keys[item["dup_of"]], "similarity": item.get("dup_similarity")})
            return out
        dedup_cmp = {
            "old_duplicate_items": o["summary"]["duplicate_items"],
            "new_duplicate_items": n["summary"]["duplicate_items"],
            "old_same_source_merges": same_source_dups(ob),
            "new_same_source_merges": same_source_dups(nb),
        }

        # 3) 百度置顶
        baidu_cmp = {
            "old_rank1": ob["baidu"]["items"][0]["title"],
            "old_rank1_is_top": bool((ob["baidu"]["items"][0].get("extra") or {}).get("is_top")),
            "new_rank1": nb["baidu"]["items"][0]["title"],
            "new_skipped": nb["baidu"]["skipped"],
        }

        # 4) 领域匹配：v0.1 子串口径 vs v0.2 规则（仅比 ASCII 关键词的差异）
        domains = new.load_domains(REPO_ROOT / "config.yaml")
        diffs = []
        for block in n["sources"]:
            for item in block["items"]:
                text = item["title"]
                desc = (item.get("extra") or {}).get("description")
                if desc and desc not in text:
                    text = f"{text} {desc}"
                for d in domains:
                    ascii_kw = [k for k in d["keywords"] if k.isascii()]
                    a = set(naive_hits(ascii_kw, text))
                    b = {k for k in ascii_kw if new.keyword_matches(k, text)}
                    if a != b:
                        diffs.append({"source": block["source"], "title": item["title"][:80],
                                      "only_old": sorted(a - b), "only_new": sorted(b - a)})
        domain_cmp = {"ascii_keyword_disagreements": diffs,
                      "items_with_domain_hits_new": sum(1 for b in n["sources"] for i in b["items"] if i.get("domain_hits"))}

        # 5) RRF Top 10（新版独有字段）
        canon = [i for b in n["sources"] for i in b["items"] if not i.get("dup_of")]
        top10 = sorted(canon, key=lambda i: (-i["fusion"]["rrf_score"], i["source"], i["rank"]))[:10]
        rrf_top = [{"title": i["title"][:60], "sources_hit": i["fusion"]["sources_hit"],
                    "rrf_score": i["fusion"]["rrf_score"]} for i in top10]

        # 6) 同事件候选：今日 + 2026-09-19 首跑（对已入库的规范化 JSON 重新计算，不联网）
        def related_pairs(items):
            pairs = []
            for a, b in itertools.combinations(items, 2):
                if a["source"] == b["source"]:
                    continue
                c = new.title_containment(a["title"], b["title"])
                if c >= new.RELATED_CONTAINMENT_MIN:
                    pairs.append({"a": f"{a['source']}#{a['rank']} {a['title'][:30]}",
                                  "b": f"{b['source']}#{b['rank']} {b['title'][:30]}", "containment": round(c, 3)})
            return pairs
        sept = json.loads((REPO_ROOT / "evals/runs_v1/live_trends_2026-09-19.json").read_text())
        sept_items = [i for b in sept["sources"] for i in b["items"] if not i.get("dup_of")]
        related_cmp = {"today_pairs": related_pairs(canon), "sept19_pairs": related_pairs(sept_items),
                       "old_version": "v0.1.1 不输出同事件候选（0 对）"}

        # 7) 连续在榜：用同一份榜单模拟"次日"与"断档 3 天后"
        def streak_after(module, seen_file: Path, day: str) -> dict:
            out = tmp / f"streak_{module.__name__}_{day}.json"
            src = old_raw if module is old else raw
            run_quiet(module, ["--offline", str(src), "--sources", "weibo", "--date", day,
                               "--seen", str(seen_file), "--output", str(out), "--quiet"])
            items = json.loads(out.read_text())["sources"][0]["items"]
            return {"streaks": sorted({i["streak"] for i in items}),
                    "gap_days": sorted({i.get("gap_days") for i in items if i.get("gap_days") is not None})}
        streak_cmp = {
            "next_day_2026-11-03": {"old": streak_after(old, old_seen, "2026-11-03"),
                                    "new": streak_after(new, new_seen, "2026-11-03")},
            "after_3_day_gap_2026-11-06": {"old": streak_after(old, old_seen, "2026-11-06"),
                                           "new": streak_after(new, new_seen, "2026-11-06")},
        }

        # 8) stdout 是否是合法 JSON（不加 --output）
        def stdout_valid(module, src):
            _, out, _ = run_quiet(module, ["--offline", str(src), "--sources", "weibo", "--date", DAY])
            try:
                json.loads(out)
                return True
            except json.JSONDecodeError:
                return False
        stdout_cmp = {"old_stdout_is_json": stdout_valid(old, old_raw),
                      "new_stdout_is_json": stdout_valid(new, raw)}

    payload = {
        "case_id": "t16",
        "date": DAY,
        "input": "2026-11-02 大陆网络，各源各 1 次真实请求的原始响应（未入库），旧版 HN 读 Algolia JSON、新版读首页 HTML",
        "raw_sha256": {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(raw.iterdir())},
        "old_version": o["tool_version"],
        "new_version": n["tool_version"],
        "summary": {"old": o["summary"], "new": n["summary"]},
        "hn_rank": hn_cmp,
        "dedup": dedup_cmp,
        "baidu_pinned": baidu_cmp,
        "domain_matching": domain_cmp,
        "rrf_top10_new": rrf_top,
        "related_candidates": related_cmp,
        "streak": streak_cmp,
        "stdout": stdout_cmp,
    }
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("summary", "hn_rank", "dedup", "baidu_pinned", "streak", "stdout")},
                     ensure_ascii=False, indent=1))
    print("domain disagreements:", len(diffs), "| related today:", len(related_cmp["today_pairs"]),
          "| related sept19:", len(related_cmp["sept19_pairs"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
