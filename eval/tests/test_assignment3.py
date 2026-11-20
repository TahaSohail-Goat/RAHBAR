import json
from types import SimpleNamespace

from eval.assignment3.coverage import compare
from eval.assignment3.gate import gate


def test_coverage_expands_when_a_new_golden_matches_uncovered_live_query() -> None:
    live = [{"id": "live-1", "domain": "in", "question": "new policy topic"}]
    before = [{"id": "old", "question": "unrelated"}]
    after = before + [{"id": "new", "question": "new policy topic"}]
    live_vector = [[1.0, 0.0]]

    old = compare(live, before, live_vector, [[0.0, 1.0]], 0.72)
    new = compare(live, after, live_vector, [[0.0, 1.0], [0.99, 0.01]], 0.72)

    assert old["coverage"] == 0.0
    assert new["coverage"] == 1.0
    assert len(old["uncovered"]) == 1


def test_out_of_scope_queries_do_not_reduce_in_scope_release_coverage() -> None:
    live = [
        {"id": "in-1", "domain": "in", "question": "policy question"},
        {"id": "out-1", "domain": "out", "question": "weather question"},
    ]
    result = compare(live, [{"id": "gold-1", "question": "policy question"}],
                     [[1.0, 0.0], [0.0, 1.0]], [[1.0, 0.0]], 0.72)

    assert result["in_scope_total"] == 1
    assert result["in_scope_coverage"] == 1.0
    assert result["coverage"] == 0.5
    assert result["out_of_scope_similarity_coverage"] == 0.0


def test_gate_coverage_is_post_expansion_metric() -> None:
    thresholds = {"max_recall5_drop": 0.02, "min_faithfulness": 0.8,
                  "min_human_faithfulness_labels": 8, "min_citation_validity": 0.95,
                  "max_latency_p95_ms": 15000, "min_abstention_correctness": 1.0,
                  "min_query_coverage": 0.85}
    baseline = {"recall@5": 0.9}
    candidate = {"recall@5": 0.9, "citation_validity": 1.0,
                 "abstention_correctness": 1.0, "latency_p95_ms": 2000,
                 "faithfulness": 1.0, "faithfulness_label_count": 8,
                 "query_coverage": 0.9, "query_coverage_before_six": 0.67}

    assert gate(candidate, baseline, thresholds) == []


def test_module_metrics_allow_list_comes_from_latest_verification(tmp_path, monkeypatch) -> None:
    from eval.assignment3.corpus import verified_corpus_sources

    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "verification-20261120T010000Z.json").write_text(
        json.dumps({"documents": [{"source": "old.md", "quarantined": False}]}),
        encoding="utf-8")
    (report_dir / "verification-20261120T020000Z.json").write_text(
        json.dumps({"documents": [{"source": "good.md", "quarantined": False},
                                   {"source": "bad.pdf", "quarantined": True}]}),
        encoding="utf-8")
    monkeypatch.setenv("RAGOPS_DATA_DIR", str(tmp_path))

    sources = verified_corpus_sources(SimpleNamespace(corpus_dir="unused"))

    assert sources == {"good.md"}


def test_gate_requires_human_faithfulness_labels_and_enforces_quality() -> None:
    thresholds = {"max_recall5_drop": 0.02, "min_faithfulness": 0.8,
                  "min_human_faithfulness_labels": 8, "min_citation_validity": 0.95,
                  "max_latency_p95_ms": 15000, "min_abstention_correctness": 1.0,
                  "min_query_coverage": 0.85}
    baseline = {"recall@5": 0.9}
    candidate = {"recall@5": 0.89, "citation_validity": 1.0,
                 "abstention_correctness": 1.0, "latency_p95_ms": 2000,
                 "faithfulness": 1.0, "faithfulness_label_count": 8,
                 "query_coverage": 0.9}

    assert gate(candidate, baseline, thresholds) == []
    candidate["faithfulness_label_count"] = 0
    failures = gate(candidate, baseline, thresholds)
    assert any("human labels" in failure for failure in failures)
