#!/usr/bin/env python3
"""从 judgments_{suite}.jsonl 汇总评测结果，写入 summary_{suite}.json（默认 v2，可 --suite v1 复算旧版）。

通过口径（rubric_v1.md）：无硬失败，且五维均值 ≥3.0（脚本层用例另需全部原子检查通过，
已在对应 judgment 的 reason 中注明）。用法：python3 evals/scripts/aggregate_results.py [--suite v1|v2]
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

EVALS = Path(__file__).resolve().parents[1]
DIMENSIONS = [
    "project_understanding",
    "real_effect",
    "iteration_improvement",
    "effect_evaluation",
    "showcase_integrity",
]


def wilson_lower_upper(successes: int, total: int, z: float = 1.96) -> list[float] | None:
    if total == 0:
        return None
    p = successes / total
    denom = 1 + z * z / total
    center = p + z * z / (2 * total)
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return [round((center - margin) / denom, 4), round((center + margin) / denom, 4)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", default="v2", choices=["v1", "v2"])
    suite = parser.parse_args().suite
    judgments = [
        json.loads(line)
        for line in (EVALS / f"judgments_{suite}.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_condition: dict[str, list] = {}
    for judgment in judgments:
        by_condition.setdefault(judgment["condition"], []).append(judgment)

    conditions = {}
    for name, rows in sorted(by_condition.items()):
        pass_count = sum(
            1
            for row in rows
            if not row["critical_failure"]
            and not row.get("failed_required_checks")
            and sum(row["scores"].values()) / len(DIMENSIONS) >= 3.0
        )
        total = len(rows)
        conditions[name] = {
            "judgment_count": total,
            "unique_case_count": len({row["case_id"] for row in rows}),
            "pass_count": pass_count,
            "pass_rate": round(pass_count / total, 4) if total else None,
            "pass_rate_wilson_95": wilson_lower_upper(pass_count, total),
            "critical_failure_count": sum(1 for row in rows if row["critical_failure"]),
            "dimension_means_0_to_4": {
                dim: round(sum(row["scores"][dim] for row in rows) / total, 3) if total else None
                for dim in DIMENSIONS
            },
        }

    skill = conditions.get("skill", {})
    baseline = conditions.get("baseline", {})
    summary = {
        "schema_version": "1.0",
        "status": "completed" if judgments else "not_run",
        "dimensions": DIMENSIONS,
        "conditions": conditions,
        "skill_minus_baseline_pass_rate": (
            round(skill["pass_rate"] - baseline["pass_rate"], 4)
            if skill.get("pass_rate") is not None and baseline.get("pass_rate") is not None
            else None
        ),
        "review_status": "model_only",
        "interpretation_note": (
            "A critical failure always fails that judgment; pass otherwise requires all "
            "atomic checks satisfied and a mean dimension score of at least 3.0/4.0. "
            "Self-assessed by the developing agent; no independent human review yet."
        ),
    }
    (EVALS / f"summary_{suite}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in summary.items() if k != "dimensions"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
