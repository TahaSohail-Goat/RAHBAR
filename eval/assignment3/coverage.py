"""Compare user-query embeddings with the golden set before and after expansion."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from indexer.pipeline.config import get_settings
from indexer.pipeline.embed import embed
from eval.assignment3.safe_paths import confined_path

ROOT = Path(__file__).resolve().parents[1]


def read(path: Path) -> list[dict[str, Any]]:
    path = confined_path(path, (ROOT,))
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    norm = math.sqrt(sum(a * a for a in left) * sum(b * b for b in right))
    return dot / norm if norm else 0.0


def compare(live: list[dict], golden: list[dict], live_vectors: list[list[float]],
            golden_vectors: list[list[float]], threshold: float) -> dict:
    result = {"threshold": threshold, "total": len(live), "covered": 0, "uncovered": []}
    by_domain: dict[str, dict[str, int]] = {}
    for row, vector in zip(live, live_vectors, strict=True):
        domain = row.get("domain", "unknown")
        group = by_domain.setdefault(domain, {"total": 0, "covered": 0})
        group["total"] += 1
        scores = [(cosine(vector, candidate), item["question"])
                  for item, candidate in zip(golden, golden_vectors, strict=True)]
        best, closest = max(scores, default=(0.0, ""))
        if best >= threshold:
            result["covered"] += 1
            group["covered"] += 1
        else:
            result["uncovered"].append({"id": row["id"], "question": row["question"],
                                        "domain": domain, "closest_golden": closest,
                                        "similarity": round(best, 5),
                                        "topic": topic(row["question"])})
    result["coverage"] = result["covered"] / len(live) if live else 0.0
    result["by_domain"] = {key: {**value, "coverage": value["covered"] / value["total"]}
                           for key, value in by_domain.items()}
    in_scope = by_domain.get("in", {"total": 0, "covered": 0})
    out_of_scope = by_domain.get("out", {"total": 0, "covered": 0})
    result["in_scope_total"] = in_scope["total"]
    result["in_scope_covered"] = in_scope["covered"]
    result["in_scope_coverage"] = (in_scope["covered"] / in_scope["total"]
                                   if in_scope["total"] else 0.0)
    result["out_of_scope_total"] = out_of_scope["total"]
    result["out_of_scope_covered"] = out_of_scope["covered"]
    result["out_of_scope_similarity_coverage"] = (
        out_of_scope["covered"] / out_of_scope["total"] if out_of_scope["total"] else 0.0)
    topics: dict[str, int] = {}
    for row in result["uncovered"]:
        topics[row["topic"]] = topics.get(row["topic"], 0) + 1
    result["uncovered_topics"] = topics
    return result


def topic(question: str) -> str:
    text = question.casefold()
    for key, words in {
        "housing": ("hostel", "curfew", "deposit"), "fees": ("tuition", "fee", "scholarship"),
        "transport": ("bus", "route", "address"), "calendar": ("convocation", "date", "weather"),
        "health_travel": ("hospital", "passport"), "finance": ("exchange", "stock", "market"),
        "campus_services": ("cafeteria", "menu", "museum"),
    }.items():
        if any(word in text for word in words):
            return key
    return "academic_policy"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", type=Path, default=ROOT / "live_queries.jsonl")
    parser.add_argument("--before", type=Path, default=ROOT / "golden.jsonl")
    parser.add_argument("--after", type=Path, default=ROOT / "golden_after_coverage.jsonl")
    parser.add_argument("--threshold", type=float, default=0.72)
    parser.add_argument("--min-coverage", type=float, default=0.85)
    args = parser.parse_args()
    args.live = confined_path(args.live, (ROOT,))
    repo_root = ROOT.resolve()
    args.before = confined_path(args.before, (repo_root,))
    args.after = confined_path(args.after, (repo_root,))
    args.out = (ROOT / "results" / "coverage.json").resolve()
    live, before, after = read(args.live), read(args.before), read(args.after)
    questions = [item["question"] for item in live + before + after]
    vectors = embed(questions, get_settings())
    n_live, n_before = len(live), len(before)
    old_vectors = vectors[n_live:n_live + n_before]
    new_vectors = vectors[n_live + n_before:]
    before_result = compare(live, before, vectors[:n_live], old_vectors, args.threshold)
    after_result = compare(live, after, vectors[:n_live], new_vectors, args.threshold)
    report = {"threshold": args.threshold,
              "justification": "0.72 is a conservative operational floor; the release gate measures in-scope coverage and reports out-of-scope similarity separately because unsupported questions must be abstained, not added to the answer corpus.",
              "before": before_result, "after": after_result,
              "minimum_coverage": args.min_coverage,
              "coverage_increased": after_result["coverage"] > before_result["coverage"]}
    if args.out != repo_root and repo_root not in args.out.parents:
        raise ValueError("coverage output escaped the repository")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["coverage_increased"] and after_result["in_scope_coverage"] >= args.min_coverage else 1


if __name__ == "__main__":
    raise SystemExit(main())
