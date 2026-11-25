"""Run module, retrieval and end-to-end RAGOps measurements against live services."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


from api.app.config import get_settings
from api.app.logjson import request_id_var
from api.app.providers.llm.ollama import OllamaProvider
from api.app.retrieval.chroma import ChromaRetriever
from api.app.services.answer import answer_question
from api.app.services.cache import SemanticCache
from api.app.tracing import finalize_trace, trace_context
from indexer.pipeline.config import get_settings as get_indexer_settings
from indexer.pipeline.embed import embed
from indexer.pipeline.run import build_chunks, prepare
from indexer.pipeline.embed import embed as embed_indexer
from eval.assignment3.coverage import compare as compare_coverage
from eval.assignment3.corpus import verified_corpus_sources
from eval.assignment3.safe_paths import confined_path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results"


def rows(path: Path) -> list[dict[str, Any]]:
    path = confined_path(path, (ROOT,))
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1)]


def embed_metrics(settings: Any) -> dict:
    pairs = rows(ROOT / "embedding_pairs.jsonl")
    texts = [item[key] for item in pairs for key in ("left", "right")]
    started = time.perf_counter()
    vectors = embed(texts, settings)
    pair_ms = (time.perf_counter() - started) * 1000 / len(texts)
    similarities = []
    for i, pair in enumerate(pairs):
        left, right = vectors[i * 2], vectors[i * 2 + 1]
        dot = sum(a * b for a, b in zip(left, right))
        norm = math.sqrt(sum(a * a for a in left) * sum(b * b for b in right))
        similarities.append((pair["kind"], dot / norm if norm else 0.0))
    repeated = embed([texts[0], texts[0]], settings)
    max_difference = max(abs(a - b) for a, b in zip(repeated[0], repeated[1]))
    documents = prepare(settings.corpus_dir,
                        allowed_sources=verified_corpus_sources(settings))
    chunks = build_chunks(documents, settings.chunk_size, settings.chunk_overlap)
    sample = [chunk.text for chunk in chunks[:min(32, len(chunks))]]
    timing_started = time.perf_counter()
    embed(sample, settings)
    per_chunk_ms = (time.perf_counter() - timing_started) * 1000 / max(1, len(sample))
    positive = [score for kind, score in similarities if kind == "paraphrase"]
    negative = [score for kind, score in similarities if kind == "unrelated"]
    return {
        "pairs": {"paraphrase_count": len(positive), "unrelated_count": len(negative),
                  "mean_paraphrase_cosine": statistics.mean(positive),
                  "mean_unrelated_cosine": statistics.mean(negative),
                  "gap": statistics.mean(positive) - statistics.mean(negative)},
        "embedding_time_ms_per_text_in_pair_experiment": round(pair_ms, 3),
        "embedding_time_ms_per_chunk_sampled": round(per_chunk_ms, 3),
        "embedding_determinism_max_abs_difference": max_difference,
        "embedding_model": settings.embed_model,
        "chunk_sample_count": len(sample),
    }


def score_response(question: dict, response: Any, seconds: float) -> dict:
    refs = question.get("relevant", [])
    retrieved = [item.model_dump(mode="json") for item in response.retrieved]

    def relevant_at(k: int) -> float | None:
        if not refs:
            return None
        return sum(any(all(item.get(key) == value for key, value in ref.items())
                       for item in retrieved[:k]) for ref in refs) / len(refs)

    ranks = []
    for ref in refs:
        rank = next((index + 1 for index, item in enumerate(retrieved)
                     if all(item.get(key) == value for key, value in ref.items())), None)
        if rank is not None:
            ranks.append(rank)
    reciprocal = max((1 / rank for rank in ranks), default=0.0) if refs else None
    dcg = sum(1 / math.log2(rank + 1) for rank in ranks[:5])
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(len(refs), 5) + 1))
    ndcg = (dcg / ideal if ideal else None)
    allowed = {(item.source, item.section, item.page) for item in response.retrieved}
    citation_valid = (bool(response.citations) and
                      all((cite.source, cite.section, cite.page) in allowed for cite in response.citations)
                      if response.answered_from_context else not response.citations)
    patterns = question.get("required_answer_patterns", [])
    answer_check = (all(required_fact_matches(pattern, response.answer) for pattern in patterns)
                    if patterns else None)
    return {
        "id": question["id"], "question": question["question"], "type": question.get("type"),
        "hard": bool(question.get("hard")), "relevant": refs,
        "response": response.model_dump(mode="json"), "seconds": round(seconds, 4),
        "recall@3": relevant_at(3), "recall@5": relevant_at(5),
        "mrr": reciprocal, "ndcg@5": ndcg,
        "citation_valid": citation_valid if response.answered_from_context else not response.citations,
        "abstention_correct": (
            not response.answered_from_context and not response.citations
            if question.get("must_abstain") else response.answered_from_context
        ),
        "required_facts_pass": answer_check,
    }


def required_fact_matches(pattern: str, answer: str) -> bool:
    """Match the golden-set mini-pattern syntax without evaluating arbitrary regexes."""
    if len(pattern) > 256 or len(answer) > 100_000:
        return False
    normalized_pattern = pattern.casefold()
    for token, replacement in ((r"\b", ""), (r"[\s-]+", " "),
                               (r"\s+", " "), (r"\s*", "")):
        normalized_pattern = normalized_pattern.replace(token, replacement)
    if "\\" in normalized_pattern or "[" in normalized_pattern or "]" in normalized_pattern:
        return False
    normalized_answer = " ".join(answer.casefold().replace("-", " ").split())
    normalized_answer = normalized_answer.replace(" %", "%")
    return " ".join(normalized_pattern.split()) in normalized_answer


def aggregate(scored: list[dict]) -> dict:
    answerable = [row for row in scored if row["relevant"]]
    citations = [row["citation_valid"] for row in scored]
    abstentions = [row["abstention_correct"] for row in scored]
    return {
        "questions": len(scored),
        "recall@3": statistics.mean(row["recall@3"] for row in answerable),
        "recall@5": statistics.mean(row["recall@5"] for row in answerable),
        "mrr": statistics.mean(row["mrr"] for row in answerable),
        "ndcg@5": statistics.mean(row["ndcg@5"] for row in answerable),
        "citation_validity": statistics.mean(citations) if citations else None,
        "abstention_correctness": statistics.mean(abstentions) if abstentions else None,
        "latency_p50_ms": round(percentile([r["seconds"] * 1000 for r in scored], .50) or 0, 2),
        "latency_p95_ms": round(percentile([r["seconds"] * 1000 for r in scored], .95) or 0, 2),
        "answer_fact_checks": sum(r["required_facts_pass"] is True for r in scored
                                   if r["required_facts_pass"] is not None),
        "answer_fact_check_count": sum(r["required_facts_pass"] is not None for r in scored),
        "faithfulness_human_labels": None,
    }


def run_queries(questions: list[dict], seed: int, settings: Any, *, traces: bool = True,
                use_cache: bool = False) -> list[dict]:
    settings = settings.model_copy(update={"llm_seed": seed}) if hasattr(settings, "model_copy") else __import__(
        "dataclasses").replace(settings, llm_seed=seed)
    retriever = ChromaRetriever(settings)
    provider = OllamaProvider(settings)
    cache = SemanticCache(settings) if use_cache else None
    scored = []
    for question in questions:
        trace_id = f"eval-{seed}-{question['id']}-{uuid.uuid4().hex[:8]}"
        token = request_id_var.set(trace_id)
        trace_token = trace_context.set({"trace_id": trace_id,
            "timestamp": datetime.now(timezone.utc).isoformat(), "stage_latency_ms": {},
            "guardrail_actions": []})
        started = time.perf_counter()
        try:
            response = answer_question(question["question"], retriever, provider, settings,
                                       cache if traces else None)
            duration = time.perf_counter() - started
            if traces:
                finalize_trace(question["question"], response, settings)
            scored.append(score_response(question, response, duration))
        finally:
            trace_context.reset(trace_token)
            request_id_var.reset(token)
    return scored


def cache_probe(question: dict, settings: Any) -> dict:
    """Run one real repeated query to record both cache miss and hit traces."""
    retriever, provider, cache = (ChromaRetriever(settings), OllamaProvider(settings),
                                  SemanticCache(settings))
    statuses = []
    for index in range(2):
        trace_id = f"cache-probe-{index}-{uuid.uuid4().hex[:8]}"
        token = request_id_var.set(trace_id)
        trace_token = trace_context.set({"trace_id": trace_id,
            "timestamp": datetime.now(timezone.utc).isoformat(), "stage_latency_ms": {},
            "guardrail_actions": []})
        try:
            response = answer_question(question["question"], retriever, provider, settings, cache)
            record = finalize_trace(question["question"], response, settings)
            statuses.append(record["cache"])
        finally:
            trace_context.reset(trace_token)
            request_id_var.reset(token)
    return {"question_id": question["id"], "statuses": statuses,
            "hit_observed": "hit" in statuses, "second_request_cached": len(statuses) == 2 and statuses[1] == "hit"}


def misspell(question: str) -> str:
    for index, word in enumerate(question.split()):
        if len(word) >= 6:
            return question.replace(word, word[:-1] + word[-1] + word[-1], 1)
    return question


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--golden", type=Path, default=ROOT / "golden.jsonl")
    parser.add_argument("--baseline", action="store_true",
                        help="write the fixed baseline.json artifact")
    parser.add_argument("--collection", default=None)
    parser.add_argument("--seed-a", type=int, default=42)
    parser.add_argument("--seed-b", type=int, default=43)
    parser.add_argument("--skip-module", action="store_true")
    args = parser.parse_args()
    allowed_data = (ROOT, Path(os.environ.get("RAGOPS_DATA_DIR", "/var/lib/rahbar")))
    args.golden = confined_path(args.golden, (ROOT,))
    if args.out is not None:
        args.out = confined_path(args.out, allowed_data)
    questions = rows(args.golden)
    settings = get_settings()
    if args.collection:
        from dataclasses import replace
        settings = replace(settings, collection=args.collection)
    index_settings = get_indexer_settings()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_a = run_queries(questions, args.seed_a, settings)
    run_b = run_queries(questions, args.seed_b, settings)
    answerable = [q for q in questions if q.get("relevant")]
    noise_rows = run_queries([dict(q, question=misspell(q["question"])) for q in answerable],
                             args.seed_a, settings, traces=False, use_cache=False)
    module = None if args.skip_module else embed_metrics(index_settings)
    live_queries = rows(ROOT / "live_queries.jsonl")
    expanded_questions = rows(ROOT / "golden_after_coverage.jsonl")
    coverage_questions = [item["question"] for item in live_queries + questions + expanded_questions]
    coverage_vectors = embed_indexer(coverage_questions, index_settings)
    n_live = len(live_queries)
    n_golden = len(questions)
    coverage = compare_coverage(live_queries, questions, coverage_vectors[:n_live],
                                coverage_vectors[n_live:n_live + n_golden], 0.72)
    expanded_coverage = compare_coverage(live_queries, expanded_questions,
        coverage_vectors[:n_live], coverage_vectors[n_live + n_golden:], 0.72)
    summary_a, summary_b, noise = aggregate(run_a), aggregate(run_b), aggregate(noise_rows)
    metric_names = ("recall@3", "recall@5", "mrr", "ndcg@5", "citation_validity",
                    "abstention_correctness", "latency_p50_ms", "latency_p95_ms")
    variance = {name: round(float(summary_b[name]) - float(summary_a[name]), 6)
                for name in metric_names if summary_a.get(name) is not None and summary_b.get(name) is not None}
    review_root = Path(os.environ.get("RAGOPS_DATA_DIR", str(ROOT / "results"))) / "reviews"
    review_root.mkdir(parents=True, exist_ok=True)
    review_path = review_root / "faithfulness_review.csv"
    previous_reviews: dict[str, dict[str, str]] = {}
    if review_path.exists():
        with review_path.open(encoding="utf-8", newline="") as stream:
            previous_reviews = {item["question_id"]: item for item in csv.DictReader(stream)}
    with review_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["question_id", "trace_id", "question", "answer", "citations",
                         "faithfulness_supported_yes_no", "reviewer", "notes"])
        for row in [item for item in run_a if item["relevant"]][:8]:
            response = row["response"]
            previous = previous_reviews.get(row["id"], {})
            writer.writerow([row["id"], response["request_id"], row["question"],
                             response["answer"], json.dumps(response["citations"], ensure_ascii=False),
                             previous.get("faithfulness_supported_yes_no", ""),
                             previous.get("reviewer", ""), previous.get("notes", "")])
    faith_labels = []
    with review_path.open(encoding="utf-8", newline="") as stream:
        for review in csv.DictReader(stream):
            value = review["faithfulness_supported_yes_no"].strip().casefold()
            if value in {"yes", "no"}:
                faith_labels.append(value == "yes")
    faithfulness = sum(faith_labels) / len(faith_labels) if len(faith_labels) >= 8 else None
    summary_a["faithfulness"] = faithfulness
    summary_a["faithfulness_label_count"] = len(faith_labels)
    summary_a["faithfulness_human_labels"] = len(faith_labels)
    # The release gate evaluates the in-scope set after the required six-question
    # expansion. Keep pre-expansion and all-live values alongside it for reporting.
    summary_a["query_coverage"] = expanded_coverage["in_scope_coverage"]
    summary_a["query_coverage_before_six"] = coverage["in_scope_coverage"]
    summary_a["query_coverage_all_live"] = coverage["coverage"]
    summary_a["query_coverage_after_six_all_live"] = expanded_coverage["coverage"]
    summary_a["coverage_in_scope_count"] = expanded_coverage["in_scope_covered"]
    summary_a["coverage_in_scope_total"] = expanded_coverage["in_scope_total"]
    summary_b["faithfulness"] = faithfulness
    summary_b["faithfulness_label_count"] = len(faith_labels)
    summary_b["faithfulness_human_labels"] = len(faith_labels)
    summary_b["query_coverage"] = expanded_coverage["in_scope_coverage"]
    summary_b["query_coverage_before_six"] = coverage["in_scope_coverage"]
    summary_b["query_coverage_all_live"] = coverage["coverage"]
    summary_b["query_coverage_after_six_all_live"] = expanded_coverage["coverage"]
    summary_b["coverage_in_scope_count"] = expanded_coverage["in_scope_covered"]
    summary_b["coverage_in_scope_total"] = expanded_coverage["in_scope_total"]
    cache_result = cache_probe(answerable[0], settings) if answerable else {
        "hit_observed": False, "second_request_cached": False, "statuses": []}
    result = {
        "schema_version": 1, "run_id": stamp, "created_at": datetime.now(timezone.utc).isoformat(),
        "golden_file": args.golden.name, "configuration": {
            "collection": settings.collection, "top_k": settings.top_k,
            "chunk_size": index_settings.chunk_size, "chunk_overlap": index_settings.chunk_overlap,
            "embed_model": settings.embed_model, "llm_model": settings.llm_model,
            "temperature": settings.temperature, "seeds": [args.seed_a, args.seed_b]},
        "module_level": module, "component_and_e2e_seed_a": {**summary_a, "rows": run_a},
        "component_and_e2e_seed_b": {**summary_b, "rows": run_b},
        "noise_test_typo_queries": {**noise, "rows": noise_rows},
        "query_coverage": coverage,
        "coverage_after_six_questions": expanded_coverage,
        "cache_probe": cache_result,
        "stochasticity_metric_differences_seed_b_minus_a": variance,
        "faithfulness_review": (f"complete: {len(faith_labels)} human judgments recorded"
                                if len(faith_labels) >= 8 else
                                f"pending: complete {review_path} for at least 8 answers"),
    }
    data_dir = Path(os.environ.get("RAGOPS_DATA_DIR", "/var/lib/rahbar"))
    output_root = data_dir / "results" if os.environ.get("RAGOPS_DATA_DIR") else OUT
    requested_name = "baseline.json" if args.baseline else f"run-{stamp}.json"
    out = output_root / requested_name
    repo_root = ROOT.resolve()
    data_root = data_dir.resolve()
    out = out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if not any(out == root or root in out.parents for root in (repo_root, data_root)):
        raise ValueError("evaluation output escaped its allowed directory")
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"result": str(out), "seed_a": summary_a, "seed_b": summary_b,
                      "noise": noise, "stochasticity": variance}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
