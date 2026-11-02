#!/usr/bin/env python3
"""运行脚本层原子检查（v1: t1-t7；v2 新增 t10-t15），产出证据 JSON。

t8（真实拉取）由当次 live 运行的产物与 JSON 内 requests 字段佐证；
t9（agent 日报）按 rubric_v1.md 人工/自评判定。全部离线，不访问网络。

用法：python3 evals/scripts/run_cases.py [--output evals/runs_v2/case_results_v2.json]
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


V2 = FIXTURES / "trends_v2"


def run_v2(tmp: Path, name: str, extra: list[str], sources: str = DEFAULT_SOURCES) -> dict:
    out = tmp / f"{name}.json"
    code = run_tool(["--offline", str(V2), "--sources", sources, "--date", "2026-11-02",
                     "--output", str(out), "--quiet", *extra])
    data = load(out)
    data["_exit"] = code
    return data


def case_t10(tmp: Path) -> list[dict]:
    data = run_v2(tmp, "t10", [], sources="hn")
    block = data["sources"][0]
    values = [i["hot_value"] for i in block["items"]]
    return [
        check("rank 为首页位置（41 分新帖第 1，2765 分老帖第 4）", values == [41, 300, 120, 2765], str(values)),
        check("招聘帖被跳过并计数", block["skipped"] == {"无分数的招聘帖": 1}, json.dumps(block["skipped"], ensure_ascii=False)),
        check("rank_basis 写明首页实际位置", "首页实际位置" in block["rank_basis"]),
        check("同源两帖（Who is hiring / Who wants to be hired）不互相合并",
              data["summary"]["duplicate_items"] == 0),
        check("HTML 实体解码", any(i["title"].startswith("Q&A: OpenAI's") for i in block["items"])),
    ]


def case_t11(tmp: Path) -> list[dict]:
    data = run_v2(tmp, "t11", [], sources="baidu")
    block = data["sources"][0]
    return [
        check("百度置顶位不占名次", [i["title"] for i in block["items"]] == ["大模型价格战再升级", "初雪预报来了"]),
        check("置顶跳过计数", block["skipped"] == {"isTop 置顶位": 1}),
    ]


def case_t12(tmp: Path) -> list[dict]:
    data = run_v2(tmp, "t12", [])
    canon = [i for b in data["sources"] for i in b["items"] if not i.get("dup_of")]
    top = max(canon, key=lambda i: i["fusion"]["rrf_score"])
    gsq = next(i for i in canon if i["title"] == "郭士强 下课")
    return [
        check("RRF 把双源话题排在单源第 1 之前", top["title"] == "大模型价格战再升级", top["title"]),
        check("rrf_score = 1/63 + 1/61", abs(top["fusion"]["rrf_score"] - (1 / 63 + 1 / 61)) < 1e-6),
        check("短词与长问句给出同事件候选", [(r["source"], r["rank"]) for r in gsq["related"]] == [("zhihu", 1)]),
        check("同事件候选不被自动合并", gsq["dup_of"] is None),
    ]


def case_t13(tmp: Path) -> list[dict]:
    data = run_v2(tmp, "t13", ["--seen", str(V2 / "seen_gap.jsonl")], sources="weibo")
    items = {i["title"]: i for i in data["sources"][0]["items"]}
    mara, llm = items["城市马拉松报名开启"], items["大模型价格战再升级"]
    return [
        check("断档 4 天后 streak 重置为 1 且 gap_days=4", mara["streak"] == 1 and mara["gap_days"] == 4,
              f"streak={mara['streak']} gap={mara['gap_days']}"),
        check("first_seen 仍保留最早日期", mara["first_seen"] == "2026-10-20"),
        check("昨天在榜则 streak+1", llm["streak"] == 3),
        check("rank_delta = 昨日 #7 − 今日 #3 = 4", llm["rank_delta"] == 4),
    ]


def case_t14(tmp: Path) -> list[dict]:
    data = run_v2(tmp, "t14", ["--config", str(V2 / "domains_config.yaml")])
    canon = {i["title"]: i for b in data["sources"] for i in b["items"]}
    hn_titles = [i for i in canon.values() if i["source"] == "hn"]
    openai = next(i for i in hn_titles if i["title"].startswith("Q&A"))
    return [
        check("中文关键词子串命中", canon["大模型价格战再升级"]["domain_hits"][0]["matched"] == ["大模型"]),
        check("OpenAI / agents 命中 AI、Agent", openai["domain_hits"][0]["matched"] == ["AI", "Agent"],
              json.dumps(openai["domain_hits"], ensure_ascii=False)),
        check("无关条目无命中", canon["城市马拉松报名开启"]["domain_hits"] == []),
        check("Complain/Bonsai 不误命中 AI",
              not ft.keyword_matches("AI", "Never Complain, Never Explain")
              and not ft.keyword_matches("AI", "Bonsai 2 27B")),
    ]


def case_t15(tmp: Path) -> list[dict]:
    import contextlib
    import io
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = ft.run(["--offline", str(V2), "--sources", "weibo", "--date", "2026-11-02"])
    try:
        json.loads(stdout.getvalue())
        valid = True
    except json.JSONDecodeError:
        valid = False
    return [
        check("未指定 --output 时 stdout 是合法 JSON", code == 0 and valid),
        check("人类可读摘要在 stderr", "微博热搜" in stderr.getvalue()),
    ]


CASES = {"t1": case_t1, "t2": case_t2, "t3": case_t3, "t4": case_t4,
         "t5": case_t5, "t6": case_t6, "t7": case_t7,
         "t10": case_t10, "t11": case_t11, "t12": case_t12, "t13": case_t13,
         "t14": case_t14, "t15": case_t15}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(REPO_ROOT / "evals/runs_v2/case_results_v2.json"))
    args = parser.parse_args()

    results = {}
    with tempfile.TemporaryDirectory() as tmp:
        for case_id in sorted(CASES, key=lambda c: int(c[1:])):
            checks = CASES[case_id](Path(tmp))
            results[case_id] = {
                "case_id": case_id,
                "passed": all(c["passed"] for c in checks),
                "checks": checks,
            }
    payload = {
        "schema_version": "1.0",
        "runner": "evals/scripts/run_cases.py",
        "case_file": "evals/cases_v2.jsonl",
        "tool_version": ft.VERSION,
        "date": "2026-11-02",
        "note": "t1-t7、t10-t15 为脚本层原子检查（离线合成夹具，不联网）；t8/t9 见 runs_v1，t16-t17 见 runs_v2 对应产物",
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
