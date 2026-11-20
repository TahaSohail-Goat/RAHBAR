"""Summarize RAGOps trace metrics over an optional ISO-8601 time window."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from pathlib import Path


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    values.sort()
    return values[min(len(values) - 1, math.ceil(fraction * len(values)) - 1)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=Path("/var/lib/rahbar/traces/queries.jsonl"))
    parser.add_argument("--since", help="ISO timestamp, inclusive")
    parser.add_argument("--until", help="ISO timestamp, inclusive")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    since = datetime.fromisoformat(args.since.replace("Z", "+00:00")) if args.since else None
    until = datetime.fromisoformat(args.until.replace("Z", "+00:00")) if args.until else None
    records = []
    for line in args.file.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        stamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
        if since and stamp < since or until and stamp > until:
            continue
        records.append(row)
    similarities = [float(row["retrieved"][0]["score"]) for row in records if row.get("retrieved")]
    stages = sorted({key for row in records for key in row.get("stage_latency_ms", {})})
    total_queries = len(records)
    hits = sum(row.get("cache") == "hit" for row in records)
    lookups = sum(row.get("cache") in {"hit", "miss"} for row in records)
    report = {
        "window": {"since": args.since, "until": args.until}, "queries": total_queries,
        "top1_similarity": {"count": len(similarities), "p50": percentile(similarities, .5),
                            "p95": percentile(similarities, .95),
                            "bins": {"<0.40": sum(score < .4 for score in similarities),
                                     "0.40-0.54": sum(.4 <= score < .55 for score in similarities),
                                     "0.55-0.69": sum(.55 <= score < .7 for score in similarities),
                                     ">=0.70": sum(score >= .7 for score in similarities)}},
        "abstention_rate": (sum(not row.get("answered_from_context", False) for row in records) /
                            total_queries if total_queries else None),
        "cache_hit_rate": hits / lookups if lookups else None,
        "cache_hits": hits, "cache_lookups": lookups,
        "stage_latency_p95_ms": {stage: percentile(
            [float(row["stage_latency_ms"][stage]) for row in records
             if row.get("stage_latency_ms", {}).get(stage) is not None], .95) for stage in stages},
        "injection_attempts_flagged": sum(int(row.get("injection_attempts_flagged", 0)) for row in records),
    }
    encoded = json.dumps(report, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
