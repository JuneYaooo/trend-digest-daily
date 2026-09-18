#!/usr/bin/env python3
"""fetch_trends.py 的单元测试：全部使用离线夹具，不访问网络。"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "fetch_trends", REPO_ROOT / "scripts" / "fetch_trends.py"
)
ft = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ft)

FIXTURES = REPO_ROOT / "evals" / "fixtures"
DEFAULT_SOURCES = "weibo,zhihu,baidu,hn"


def run_tool(argv: list[str]):
    """运行主入口，返回 (退出码, 输出 JSON 或 None)。"""
    exit_code = ft.run(argv)
    return exit_code


def load_json(path: str | Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class HelperTests(unittest.TestCase):
    def test_title_duplicate_variants(self):
        self.assertTrue(ft.titles_duplicate("AI编程工具被曝上传用户代码", "#AI编程工具被曝上传用户代码#"))
        self.assertTrue(
            ft.titles_duplicate("新一代折叠屏手机发布", "如何看待新一代折叠屏手机发布的影像方案？")
        )
        self.assertFalse(ft.titles_duplicate("城市马拉松报名开启", "全国养老服务新政落地"))
        self.assertFalse(ft.titles_duplicate("", "随便什么标题"))

    def test_normalize_url(self):
        self.assertEqual(
            ft.normalize_url("http://www.example.com/a/b/?utm_source=x&id=3"),
            "https://example.com/a/b?id=3",
        )
        self.assertEqual(
            ft.normalize_url("https://api.zhihu.com/questions/12345?utm_source=x"),
            "https://www.zhihu.com/question/12345",
        )
        self.assertIsNone(ft.normalize_url(None))
        self.assertIsNone(ft.normalize_url("/relative/path"))

    def test_num_or_none(self):
        self.assertEqual(ft.num_or_none("1595 万热度"), 15950000)
        self.assertEqual(ft.num_or_none("1,234"), 1234)
        self.assertEqual(ft.num_or_none(42), 42)
        self.assertIsNone(ft.num_or_none("热度未知"))
        self.assertIsNone(ft.num_or_none(None))

    def test_item_key_stable(self):
        key_a = ft.item_key("https://example.com/a?utm_source=x", "标题甲")
        key_b = ft.item_key("https://example.com/a", "标题甲")
        self.assertEqual(key_a, key_b)
        # 无 URL 时按标题生成 key，且两个不同标题不同 key
        self.assertNotEqual(ft.item_key(None, "标题甲"), ft.item_key(None, "标题乙"))


class RequestBudgetTests(unittest.TestCase):
    def test_single_request_budget(self):
        ctx = ft.SourceContext("hn", limit=5, timeout=1.0, date_iso="2026-09-19")
        with self.assertRaises(ft.FetchError):
            ctx.http_get("https://127.0.0.1:9/unreachable", {})
        # 即使第一次请求失败，预算也已被消耗：不允许第二次请求
        with self.assertRaises(ft.FetchError):
            ctx.http_get("https://127.0.0.1:9/unreachable", {})
        self.assertEqual(ctx.request_count, 1)

    def test_offline_missing_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = ft.SourceContext("hn", limit=5, timeout=1.0, date_iso="2026-09-19",
                                   offline_dir=Path(tmp))
            with self.assertRaises(ft.FetchError):
                ctx.fixture_text("hn")


class OfflineRunTests(unittest.TestCase):
    """主夹具 trends_v1：三源有数据（含跨源重复、广告位），百度 500 错误。"""

    def test_full_run_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "trends.json"
            code = run_tool([
                "--offline", str(FIXTURES / "trends_v1"),
                "--sources", DEFAULT_SOURCES,
                "--date", "2026-09-19",
                "--output", str(out), "--quiet",
            ])
            self.assertEqual(code, 0)
            data = load_json(out)
            self.assertEqual(data["mode"], "offline")
            self.assertEqual(data["fetched_date"], "2026-09-19")
            by_source = {block["source"]: block for block in data["sources"]}
            self.assertEqual(by_source["weibo"]["status"], "ok")
            self.assertEqual(by_source["zhihu"]["status"], "ok")
            self.assertEqual(by_source["hn"]["status"], "ok")
            self.assertEqual(by_source["baidu"]["status"], "unavailable")
            self.assertIn("500", by_source["baidu"]["error"])
            # 百度失败不影响其他源；离线模式 requests=0（未联网）
            self.assertEqual(by_source["baidu"]["requests"], 0)
            summary = data["summary"]
            # 微博 5 条（广告位跳过）+ 知乎 5 + HN 5 = 15
            self.assertEqual(summary["total_items"], 15)
            self.assertEqual(summary["duplicate_items"], 2)
            self.assertEqual(summary["unique_items"], 13)
            self.assertEqual(summary["sources_ok"], 3)
            self.assertEqual(summary["sources_unavailable"], 1)

    def test_cross_source_duplicates_marked(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "trends.json"
            run_tool(["--offline", str(FIXTURES / "trends_v1"), "--date", "2026-09-19",
                      "--output", str(out), "--quiet"])
            data = load_json(out)
            by_source = {b["source"]: b for b in data["sources"]}
            zhihu_dups = [i for i in by_source["zhihu"]["items"] if i.get("dup_of")]
            self.assertEqual(len(zhihu_dups), 2)
            # 主条目应来自微博（CANONICAL_ORDER 靠前），dup_similarity 达阈值
            weibo_titles = {i["title"] for i in by_source["weibo"]["items"]}
            for dup in zhihu_dups:
                self.assertIn(dup["dup_of_title"], weibo_titles)
                self.assertGreaterEqual(dup["dup_similarity"], 0.5)

    def test_weibo_adapter_cleans_topic_and_skips_ads(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "trends.json"
            run_tool(["--offline", str(FIXTURES / "trends_v1"), "--sources", "weibo",
                      "--date", "2026-09-19", "--output", str(out), "--quiet"])
            data = load_json(out)
            items = data["sources"][0]["items"]
            titles = [i["title"] for i in items]
            self.assertNotIn("#AI编程工具被曝上传用户代码#", titles)  # 话题外壳已清洗
            self.assertFalse(any("限时大促" in t for t in titles))  # 广告位跳过
            first = items[0]
            self.assertEqual(first["rank"], 1)
            self.assertEqual(first["hot_label"], "爆")
            self.assertEqual(first["hot_value"], 1873452)
            self.assertTrue(first["url"].startswith("https://s.weibo.com/weibo?q="))

    def test_hn_null_url_falls_back_to_story_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "trends.json"
            run_tool(["--offline", str(FIXTURES / "trends_v1"), "--sources", "hn",
                      "--date", "2026-09-19", "--output", str(out), "--quiet"])
            data = load_json(out)
            items = data["sources"][0]["items"]
            no_url = [i for i in items if i["title"] == "The hidden cost of cloud egress"]
            self.assertEqual(len(no_url), 1)
            self.assertEqual(no_url[0]["url"], "https://news.ycombinator.com/item?id=9002")

    def test_zhihu_url_rewrite_and_heat(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "trends.json"
            run_tool(["--offline", str(FIXTURES / "trends_v1"), "--sources", "zhihu",
                      "--date", "2026-09-19", "--output", str(out), "--quiet"])
            data = load_json(out)
            items = data["sources"][0]["items"]
            self.assertEqual(items[0]["url"], "https://www.zhihu.com/question/109001")
            self.assertEqual(items[0]["hot_value"], 48210000)
            self.assertEqual(items[0]["hot_value_raw"], "4821 万热度")
            self.assertEqual(items[0]["hot_label"], "热")

    def test_baidu_error_body_marks_source_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "trends.json"
            code = run_tool(["--offline", str(FIXTURES / "trends_v1"), "--sources", "baidu",
                             "--date", "2026-09-19", "--output", str(out), "--quiet"])
            # 仅剩一个源且失败 → 全部源不可用 → 退出码 3
            self.assertEqual(code, 3)
            data = load_json(out)
            block = data["sources"][0]
            self.assertEqual(block["status"], "unavailable")
            self.assertIn("缺少 data", block["error"])
            self.assertEqual(block["items"], [])


class SeenTests(unittest.TestCase):
    def test_new_and_streak_marking(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "trends.json"
            seen_out = Path(tmp) / "seen_out.jsonl"
            code = run_tool([
                "--offline", str(FIXTURES / "trends_v1"),
                "--sources", "weibo",
                "--date", "2026-09-19",
                "--seen", str(FIXTURES / "seen_day1.jsonl"),
                "--seen-out", str(seen_out),
                "--output", str(out), "--quiet",
            ])
            self.assertEqual(code, 0)
            data = load_json(out)
            items = {i["title"]: i for i in data["sources"][0]["items"]}
            # 标题变体命中缓存：streak 累加、first_seen 保留、非 NEW
            typhoon = items["台风“山陀儿”逼近华南沿海"]
            self.assertFalse(typhoon["is_new"])
            self.assertEqual(typhoon["streak"], 3)
            self.assertEqual(typhoon["first_seen"], "2026-09-17")
            # 精确同名命中：streak +1
            elder = items["全国养老服务新政落地"]
            self.assertFalse(elder["is_new"])
            self.assertEqual(elder["streak"], 2)
            # 昨日未上榜的条目：NEW
            fresh = items["AI编程工具被曝上传用户代码，官方深夜回应"]
            self.assertTrue(fresh["is_new"])
            self.assertEqual(fresh["first_seen"], "2026-09-19")
            # seen-out：今日上榜条目被收录，已冷却条目保留（30 天内）
            seen_lines = [json.loads(line) for line in seen_out.read_text(encoding="utf-8").splitlines()]
            seen_entries = {entry["title"]: entry for entry in seen_lines}
            # 5 条今日主条目（2 条更新旧行 + 3 条新增）+ 1 条已冷却旧条目 = 6 行，无重复行
            self.assertEqual(len(seen_lines), 6)
            self.assertEqual(len({entry["key"] for entry in seen_lines}), 6)
            self.assertIn("AI编程工具被曝上传用户代码，官方深夜回应", seen_entries)
            self.assertIn("某款老应用宣布停止运营", seen_entries)
            self.assertEqual(seen_entries["全国养老服务新政落地"]["streak"], 2)
            self.assertEqual(seen_entries["台风“山陀儿”逼近华南沿海"]["streak"], 3)

    def test_first_run_without_seen_marks_all_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "trends.json"
            code = run_tool(["--offline", str(FIXTURES / "trends_v1"), "--sources", "weibo",
                             "--date", "2026-09-19", "--output", str(out), "--quiet"])
            self.assertEqual(code, 0)
            data = load_json(out)
            self.assertEqual(data["summary"]["new_items"], data["summary"]["unique_items"])


class BoundaryTests(unittest.TestCase):
    def test_empty_board_ok_sources_exit_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "trends.json"
            code = run_tool([
                "--offline", str(FIXTURES / "trends_empty_v1"),
                "--sources", DEFAULT_SOURCES,
                "--date", "2026-09-19",
                "--output", str(out), "--quiet",
            ])
            self.assertEqual(code, 0)
            data = load_json(out)
            by_source = {b["source"]: b for b in data["sources"]}
            self.assertEqual(by_source["zhihu"]["status"], "ok")
            self.assertEqual(by_source["zhihu"]["item_count"], 0)
            self.assertEqual(by_source["hn"]["status"], "ok")
            self.assertEqual(by_source["hn"]["item_count"], 0)
            # 空列表对微博按结构异常降级
            self.assertEqual(by_source["weibo"]["status"], "unavailable")
            self.assertEqual(data["summary"]["total_items"], 0)
            self.assertEqual(data["summary"]["unique_items"], 0)

    def test_all_sources_unavailable_exit_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "trends.json"
            code = run_tool([
                "--offline", str(FIXTURES / "trends_all_error_v1"),
                "--sources", DEFAULT_SOURCES,
                "--date", "2026-09-19",
                "--output", str(out), "--quiet",
            ])
            self.assertEqual(code, 3)
            data = load_json(out)  # 仍输出合法 JSON，逐源给出中文错误
            self.assertEqual(data["summary"]["sources_ok"], 0)
            for block in data["sources"]:
                self.assertEqual(block["status"], "unavailable")
                self.assertTrue(block["error"])

    def test_missing_offline_dir_exit_two(self):
        code = run_tool(["--offline", "/nonexistent_dir_xyz", "--date", "2026-09-19", "--quiet"])
        self.assertEqual(code, 2)

    def test_unknown_source_exit_two(self):
        code = run_tool(["--sources", "weibo,myspace", "--offline",
                         str(FIXTURES / "trends_v1"), "--quiet"])
        self.assertEqual(code, 2)

    def test_bad_date_exit_two(self):
        code = run_tool(["--date", "2026-13-99", "--quiet"])
        self.assertEqual(code, 2)


class DeterminismTests(unittest.TestCase):
    def test_offline_run_is_deterministic(self):
        digests = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "trends.json"
                code = run_tool([
                    "--offline", str(FIXTURES / "trends_v1"),
                    "--sources", DEFAULT_SOURCES,
                    "--date", "2026-09-19",
                    "--seen", str(FIXTURES / "seen_day1.jsonl"),
                    "--output", str(out), "--quiet",
                ])
                self.assertEqual(code, 0)
                import hashlib

                digests.append(hashlib.sha256(out.read_bytes()).hexdigest())
        self.assertEqual(digests[0], digests[1])


class OptionalSourceTests(unittest.TestCase):
    def test_github_trending_html_parse(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "trends.json"
            code = run_tool([
                "--offline", str(FIXTURES / "trends_optional_v1"),
                "--sources", "github_trending",
                "--date", "2026-09-19", "--output", str(out), "--quiet",
            ])
            self.assertEqual(code, 0)
            data = load_json(out)
            items = data["sources"][0]["items"]
            self.assertEqual(items[0]["title"], "acme/edge-router：A tiny reverse proxy written in Go")
            self.assertEqual(items[0]["hot_value"], 1204)
            self.assertEqual(items[0]["url"], "https://github.com/acme/edge-router")
            self.assertEqual(items[1]["rank"], 2)

    def test_reddit_parse_skips_sticky(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "trends.json"
            code = run_tool([
                "--offline", str(FIXTURES / "trends_optional_v1"),
                "--sources", "reddit",
                "--date", "2026-09-19", "--output", str(out), "--quiet",
            ])
            self.assertEqual(code, 0)
            data = load_json(out)
            items = data["sources"][0]["items"]
            self.assertEqual(len(items), 2)
            self.assertTrue(items[0]["url"].startswith("https://www.reddit.com/r/socialmedia/"))
            self.assertEqual(items[0]["hot_value"], 2841)


if __name__ == "__main__":
    unittest.main()
