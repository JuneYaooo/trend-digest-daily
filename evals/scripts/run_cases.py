#!/usr/bin/env python3
"""运行 cases_v1.jsonl 中脚本层的原子检查（t1-t7），产出证据 JSON。

t8（真实拉取）由当次 live 运行的产物与 JSON 内 requests 字段佐证；
t9（agent 日报）按 rubric_v1.md 人工/自评判定。全部离线，不访问网络。

用法：python3 evals/scripts/run_cases.py [--output evals/runs_v1/case_results_v1.json]
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "fetch_trends", REPO_ROOT / "scripts" / "fetch_trends.py"
)
ft = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ft)

FIXTURES = REPO_ROOT / "evals" / "fixtures"
DEFAULT_SOURCES = "weibo,zhihu,baidu,hn"


def run_tool(argv: list[str]) -> int:
    return ft.run(argv)


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def check(name: str, ok: bool, detail: str = "") -> dict:
    return {"check": name, "passed": bool(ok), "detail": detail}


def by_source(data: dict) -> dict:
    return {block["source"]: block for block in data["sources"]}


def case_t1(tmp: Path) -> list[dict]:
    out = tmp / "t1.json"
    code = run_tool(["--offline", str(FIXTURES / "trends_v1"), "--sources", DEFAULT_SOURCES,
                     "--date", "2026-09-19", "--output", str(out), "--quiet"])
    data = load(out)
    src = by_source(data)
    s = data["summary"]
    return [
        check("退出码 0", code == 0, f"exit={code}"),
        check("四源均在输出中", set(src) == {"weibo", "zhihu", "baidu", "hn"}, str(list(src))),
        check("微博/知乎/HN ok 且有条目",
              all(src[k]["status"] == "ok" and src[k]["item_count"] > 0 for k in ("weibo", "zhihu", "hn"))),
        check("百度标注不可用并给中文错误",
              src["baidu"]["status"] == "unavailable" and "500" in (src["baidu"]["error"] or ""),
              src["baidu"]["error"] or ""),
        check("汇总 15 条/重复 2/唯一 13",
              (s["total_items"], s["duplicate_items"], s["unique_items"]) == (15, 2, 13), json.dumps(s, ensure_ascii=False)),
        check("条目含 rank/title/url 规范字段",
              all(all(k in i for k in ("rank", "title", "url", "hot_value"))
                  for blk in data["sources"] for i in blk["items"])),
    ]


def case_t2(tmp: Path) -> list[dict]:
    out = tmp / "t2.json"
    seen_out = tmp / "seen_out.jsonl"
    code = run_tool(["--offline", str(FIXTURES / "trends_v1"), "--sources", "weibo",
                     "--date", "2026-09-19", "--seen", str(FIXTURES / "seen_day1.jsonl"),
                     "--seen-out", str(seen_out), "--output", str(out), "--quiet"])
    data = load(out)
    items = {i["title"]: i for i in data["sources"][0]["items"]}
    lines = [json.loads(l) for l in seen_out.read_text(encoding="utf-8").splitlines()]
    return [
        check("退出码 0", code == 0),
        check("标题变体命中缓存：台风 streak=3、非 NEW、first_seen 保留",
              not items["台风“山陀儿”逼近华南沿海"]["is_new"]
              and items["台风“山陀儿”逼近华南沿海"]["streak"] == 3
              and items["台风“山陀儿”逼近华南沿海"]["first_seen"] == "2026-09-17"),
        check("昨日已见条目：养老服务 streak=2、非 NEW",
              not items["全国养老服务新政落地"]["is_new"]
              and items["全国养老服务新政落地"]["streak"] == 2),
        check("新条目标 NEW", items["AI编程工具被曝上传用户代码，官方深夜回应"]["is_new"]),
        check("seen-out 6 行且 key 无重复（旧条目原地更新）",
              len(lines) == 6 and len({l["key"] for l in lines}) == 6),
        check("已冷却条目保留在缓存", any(l["title"] == "某款老应用宣布停止运营" for l in lines)),
    ]


def case_t3(tmp: Path) -> list[dict]:
    out = tmp / "t3.json"
    code = run_tool(["--offline", str(FIXTURES / "trends_v1"), "--sources", DEFAULT_SOURCES,
                     "--date", "2026-09-19", "--output", str(out), "--quiet"])
    data = load(out)
    src = by_source(data)
    return [
        check("退出码 0（单源失败不拖垮整体）", code == 0),
        check("其他三源 items 不为空",
              all(src[k]["item_count"] > 0 for k in ("weibo", "zhihu", "hn"))),
        check("百度错误为中文说明", "500" in (src["baidu"]["error"] or "")),
        check("汇总 sources_unavailable=1", data["summary"]["sources_unavailable"] == 1),
    ]


def case_t4(tmp: Path) -> list[dict]:
    out = tmp / "t4.json"
    code = run_tool(["--offline", str(FIXTURES / "trends_empty_v1"), "--sources", DEFAULT_SOURCES,
                     "--date", "2026-09-19", "--output", str(out), "--quiet"])
    data = load(out)
    src = by_source(data)
    s = data["summary"]
    return [
        check("退出码 0（有空榜源成功即成功）", code == 0),
        check("知乎/HN 状态 ok 且 0 条", src["zhihu"]["status"] == "ok" and src["zhihu"]["item_count"] == 0
              and src["hn"]["status"] == "ok" and src["hn"]["item_count"] == 0),
        check("汇总全零且不崩溃", (s["total_items"], s["unique_items"]) == (0, 0)),
        check("输出为合法 JSON（可被下游消费）", isinstance(data, dict) and "sources" in data),
    ]


def case_t5(tmp: Path) -> list[dict]:
    out = tmp / "t5.json"
    code = run_tool(["--offline", str(FIXTURES / "trends_all_error_v1"), "--sources", DEFAULT_SOURCES,
                     "--date", "2026-09-19", "--output", str(out), "--quiet"])
    data = load(out)
    return [
        check("全部源不可用时退出码 3", code == 3, f"exit={code}"),
        check("仍输出合法 JSON", "sources" in data),
        check("每源给出中文错误", all(b["status"] == "unavailable" and b["error"] for b in data["sources"])),
        check("sources_ok=0", data["summary"]["sources_ok"] == 0),
    ]


def case_t6(tmp: Path) -> list[dict]:
    digests = []
    for run_index in range(2):
        out = tmp / f"t6_run{run_index}.json"
        code = run_tool(["--offline", str(FIXTURES / "trends_v1"), "--sources", DEFAULT_SOURCES,
                         "--date", "2026-09-19", "--seen", str(FIXTURES / "seen_day1.jsonl"),
                         "--output", str(out), "--quiet"])
        if code != 0:
            return [check("退出码 0", False, f"run{run_index} exit={code}")]
        digests.append(hashlib.sha256(out.read_bytes()).hexdigest())
    return [
        check("两次 --offline 运行退出码 0", True),
        check("输出 sha256 一致", digests[0] == digests[1], digests[0][:16] + "…"),
    ]


def case_t7(tmp: Path) -> list[dict]:
    out = tmp / "t7.json"
    run_tool(["--offline", str(FIXTURES / "trends_v1"), "--sources", DEFAULT_SOURCES,
              "--date", "2026-09-19", "--output", str(out), "--quiet"])
    data = load(out)
    src = by_source(data)
    dups = [i for i in src["zhihu"]["items"] if i.get("dup_of")]
    weibo_titles = {i["title"] for i in src["weibo"]["items"]}
    distinct = [i for i in src["zhihu"]["items"] if not i.get("dup_of")]
    hn_dups = [i for i in src["hn"]["items"] if i.get("dup_of")]
    return [
        check("知乎 2 条被标记跨源重复", len(dups) == 2),
        check("dup_of 主条目均来自微博且相似度≥0.5",
              all(d["dup_of_title"] in weibo_titles and d["dup_similarity"] >= 0.5 for d in dups)),
        check("不同事件未被误并（知乎其余 3 条独立）", len(distinct) == 3),
        check("英文与中文条目零误并", len(hn_dups) == 0),
    ]


CASES = {"t1": case_t1, "t2": case_t2, "t3": case_t3, "t4": case_t4,
         "t5": case_t5, "t6": case_t6, "t7": case_t7}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(REPO_ROOT / "evals/runs_v1/case_results_v1.json"))
    args = parser.parse_args()

    results = {}
    with tempfile.TemporaryDirectory() as tmp:
        for case_id in sorted(CASES):
            checks = CASES[case_id](Path(tmp))
            results[case_id] = {
                "case_id": case_id,
                "passed": all(c["passed"] for c in checks),
                "checks": checks,
            }
    payload = {
        "schema_version": "1.0",
        "runner": "evals/scripts/run_cases.py",
        "case_file": "evals/cases_v1.jsonl",
        "date": "2026-09-19",
        "note": "t1-t7 为脚本层原子检查（离线夹具，不联网）；t8/t9 证据见 runs_v1 对应产物",
        "results": results,
        "passed_cases": sum(1 for r in results.values() if r["passed"]),
        "total_cases": len(results),
    }
    output = Path(args.output)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for case_id, result in results.items():
        marker = "PASS" if result["passed"] else "FAIL"
        print(f"[{marker}] {case_id}: {sum(c['passed'] for c in result['checks'])}/{len(result['checks'])} checks")
        for c in result["checks"]:
            if not c["passed"]:
                print(f"    ✗ {c['check']} {c.get('detail', '')}")
    print(f"\n{payload['passed_cases']}/{payload['total_cases']} script-level cases passed")
    return 0 if payload["passed_cases"] == payload["total_cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
