"""Compare a candidate result with the baseline using a runtime YAML gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import os

import yaml

from eval.assignment3.safe_paths import confined_path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(os.environ.get("RAGOPS_DATA_DIR", "/var/lib/rahbar"))


def summary(result: dict) -> dict:
    return result.get("summary", result.get("component_and_e2e_seed_a", result))


def gate(candidate: dict, baseline: dict, thresholds: dict) -> list[str]:
    candidate, baseline = summary(candidate), summary(baseline)
    failures = []
    if candidate.get("recall@5") is None or baseline.get("recall@5") is None:
        failures.append("recall@5 missing")
    elif baseline["recall@5"] - candidate["recall@5"] > float(thresholds["max_recall5_drop"]):
        failures.append("recall@5 regression exceeds configured allowance")
    citation = candidate.get("citation_validity")
    if citation is None or citation < float(thresholds["min_citation_validity"]):
        failures.append("citation validity is below configured minimum")
    abstention = candidate.get("abstention_correctness")
    if abstention is None or abstention < float(thresholds["min_abstention_correctness"]):
        failures.append("abstention correctness is below configured minimum")
    latency = candidate.get("latency_p95_ms")
    if latency is None or latency > float(thresholds["max_latency_p95_ms"]):
        failures.append("p95 latency exceeds configured maximum")
    faithfulness = candidate.get("faithfulness")
    labels = int(candidate.get("faithfulness_label_count", 0))
    if labels < int(thresholds["min_human_faithfulness_labels"]):
        failures.append(f"faithfulness needs at least {thresholds['min_human_faithfulness_labels']} human labels; got {labels}")
    elif faithfulness is None or faithfulness < float(thresholds["min_faithfulness"]):
        failures.append("human-reviewed faithfulness is below configured minimum")
    coverage = candidate.get("query_coverage")
    if coverage is not None and coverage < float(thresholds["min_query_coverage"]):
        failures.append("query coverage is below configured minimum")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--thresholds", type=Path,
                        default=Path(__file__).with_name("gate.yaml"))
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    allowed = (REPO_ROOT, DATA_ROOT, Path("/etc/rahbar/gates"))
    args.candidate = confined_path(args.candidate, allowed)
    args.baseline = confined_path(args.baseline, allowed)
    args.thresholds = confined_path(args.thresholds, (REPO_ROOT, Path("/etc/rahbar/gates")))
    if args.out is not None:
        args.out = args.out.resolve()
        repo_root = REPO_ROOT.resolve()
        data_root = DATA_ROOT.resolve()
        if not any(args.out == root or root in args.out.parents
                   for root in (repo_root, data_root)):
            raise ValueError("gate output must remain inside the repository or data directory")
    thresholds = yaml.safe_load(args.thresholds.read_text(encoding="utf-8"))
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    failures = gate(candidate, baseline, thresholds)
    report = {"candidate": str(args.candidate), "baseline": str(args.baseline),
              "thresholds": thresholds, "decision": "reject" if failures else "release",
              "failures": failures}
    encoded = json.dumps(report, indent=2) + "\n"
    if args.out:
        if not any(args.out == root or root in args.out.parents
                   for root in (REPO_ROOT.resolve(), DATA_ROOT.resolve())):
            raise ValueError("gate output escaped its allowed directory")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
