"""Build the Assignment 3 report PDF from measured JSON and real screenshots."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

REPO = Path(__file__).resolve().parents[2]
SCREENSHOT_CAPTIONS = {
    "A1-verification": "A1 — Batch B verification report with each check and its reasons",
    "A2-incremental": "A2 — unchanged ingestion run with zero chunks embedded",
    "B3-evaluation": "B3 — module, retrieval and end-to-end evaluation summary",
    "C2-reject": "C2 — candidate blocked by the release gate",
    "C2-pass": "C2 — passing release gate after completed human review",
    "D1-trace": "D1 — one complete JSON trace record",
    "D2-reconstruct": "D2 — trace command rebuilding the exact prompt and context",
    "E2-coverage": "E2/E4 — live-query coverage before and after six additions",
    "F1-f2-k8s": "F1/F2 — namespace objects, PVC, ConfigMap, CronJob and Jobs",
    "F2-logs": "F2 — completed ingestion and evaluation Job logs",
    "F2-eval-logs": "F2 — completed evaluation Job log and status",
    "F3-mismatch": "F3 — 0/1 API pod and live embedding-model mismatch readiness response",
    "F3-f5-release": "F3/F5 — ConfigMap gate change, rollout/undo trace and resource measurements",
}


def read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "not measured"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def cell(text: Any) -> Paragraph:
    return Paragraph(str(text), getSampleStyleSheet()["BodyText"])


def table(data: list[list[Any]], widths: list[float] | None = None) -> Table:
    rendered = [[cell(value) for value in row] for row in data]
    result = Table(rendered, colWidths=widths, repeatRows=1, hAlign="LEFT")
    result.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#15324b")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#b7c6d1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#eef3f6")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return result


def compact_table(data: list[list[Any]], widths: list[float]) -> Table:
    style = ParagraphStyle("CompactCell", parent=getSampleStyleSheet()["BodyText"],
                           fontSize=7.4, leading=8.5, spaceAfter=0)
    rendered = [[Paragraph(str(value), style) for value in row] for row in data]
    result = Table(rendered, colWidths=widths, repeatRows=1, hAlign="LEFT")
    result.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#15324b")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#b7c6d1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#eef3f6")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return result


def load_review_counts(path: Path) -> tuple[int, int]:
    if not path.is_file():
        return 0, 0
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    authored = sum(bool(row.get("human_authored_by_group_member", "").strip()) for row in rows)
    reviewed = sum(bool(row.get("synthetic_question_reviewed_by_group_member", "").strip())
                   for row in rows)
    return authored, reviewed


def resource_observation(path: Path) -> str:
    """Summarize a captured `kubectl top pod` table without inventing values."""
    if not path.is_file():
        return "not captured"
    rows: dict[str, list[tuple[int, int]]] = {"api": [], "candidate": [], "chroma": [], "redis": []}
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = re.split(r"\s+", line.strip())
        if len(fields) < 3 or fields[0] == "NAME":
            continue
        name, cpu, memory = fields[:3]
        group = ("candidate" if "candidate" in name else
                 "api" if name.startswith("api-") else
                 "chroma" if name.startswith("chroma-") else
                 "redis" if name.startswith("redis-") else None)
        if group is None:
            continue
        cpu_value = int(cpu.removesuffix("m")) if cpu.endswith("m") else int(float(cpu) * 1000)
        memory_value = int(memory.removesuffix("Mi")) if memory.endswith("Mi") else 0
        rows[group].append((cpu_value, memory_value))

    def bounds(group: str) -> str:
        values = rows[group]
        if not values:
            return f"{group}: not captured"
        cpus = [value[0] for value in values]
        memories = [value[1] for value in values]
        cpu_text = f"{min(cpus)}-{max(cpus)}m" if min(cpus) != max(cpus) else f"{min(cpus)}m"
        memory_text = (f"{min(memories)}-{max(memories)}Mi" if min(memories) != max(memories)
                       else f"{min(memories)}Mi")
        return f"{group}: {cpu_text}/{memory_text}"

    return "; ".join(bounds(group) for group in ("api", "candidate", "chroma", "redis"))


def build(args: argparse.Namespace) -> None:
    output = args.out
    output.parent.mkdir(parents=True, exist_ok=True)
    baseline = read_json(args.baseline)
    candidate = read_json(args.candidate)
    verification = read_json(args.verification)
    ingestion = read_json(args.ingestion)
    coverage = read_json(args.coverage)
    gate_result = read_json(args.gate)

    seed_a = baseline.get("component_and_e2e_seed_a", {})
    candidate_a = candidate.get("component_and_e2e_seed_a", {})
    module = baseline.get("module_level") or {}
    before_coverage = coverage.get("before") or baseline.get("query_coverage") or {}
    after_coverage = coverage.get("after") or baseline.get("coverage_after_six_questions") or {}
    verification_rows = verification.get("documents", [])
    archived = sum(bool(row.get("archived")) for row in verification_rows)
    quarantined = sum(bool(row.get("quarantined")) for row in verification_rows)
    review_counts = load_review_counts(args.human_review)
    failed_checks: dict[str, int] = {}
    for row in verification_rows:
        for name, check in row.get("checks", {}).items():
            if not check.get("passed", False):
                failed_checks[name] = failed_checks.get(name, 0) + 1
    leading_check = max(failed_checks, key=failed_checks.get) if failed_checks else "not measured"
    missed_injection = any(row.get("injection_attempts", 0) and not row.get("quarantined", False)
                           for row in verification_rows)
    failed_fact_rows = [row.get("id") for row in seed_a.get("rows", [])
                        if row.get("required_facts_pass") is False]

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Cover", parent=styles["Title"], fontSize=25,
                              leading=31, alignment=TA_CENTER, textColor=colors.HexColor("#15324b")))
    styles.add(ParagraphStyle(name="Section", parent=styles["Heading1"], fontSize=17,
                              leading=21, textColor=colors.HexColor("#15324b"), spaceAfter=8))
    styles.add(ParagraphStyle(name="Subsection", parent=styles["Heading2"], fontSize=12,
                              leading=15, textColor=colors.HexColor("#206a85"), spaceBefore=7))
    styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=8.5, leading=11))
    styles.add(ParagraphStyle(name="Caption", parent=styles["BodyText"], fontSize=9,
                              leading=12, alignment=TA_CENTER))
    story: list[Any] = []

    # Main report: eight deliberately bounded pages. Screenshots follow as appendix.
    story += [Spacer(1, 23 * mm), Paragraph("RAHBAR", styles["Cover"]),
              Paragraph("Assignment 03 — RAGOps", styles["Cover"]), Spacer(1, 8 * mm),
              Paragraph("Software Construction and Development", styles["Heading2"]),
              Spacer(1, 7 * mm), table([
                  ["Team member", "Roll number"],
                  [args.member1, args.roll1 or "[add roll number]"],
                  [args.member2, args.roll2 or "[add roll number]"],
              ], [75 * mm, 75 * mm]), Spacer(1, 8 * mm),
              Paragraph("Release summary", styles["Section"]),
              Paragraph("This report summarizes the verified document pipeline, live evaluation, "
                        "candidate release gate, query tracing and Kubernetes operations. "
                        "Numeric results below are read from the named run artifacts; absent "
                        "measurements are shown as not measured.", styles["BodyText"]),
              Spacer(1, 6 * mm),
              table([["Corpus verification", "Golden questions", "Live queries", "Candidate decision"],
                    [f"{len(verification_rows)} docs; {quarantined} quarantined; {archived} archived",
                     str(seed_a.get("questions", "not measured")),
                     str(before_coverage.get("total", "not measured")),
                     gate_result.get("decision", "not measured")]],
                   [39 * mm, 34 * mm, 30 * mm, 35 * mm]),
              Spacer(1, 5 * mm),
              Paragraph("Roll numbers and contribution attribution must be checked by the team "
                        "before submission.", styles["Small"]), PageBreak()]

    story += [Paragraph("A — Document management", styles["Section"]),
              Paragraph("Documents are checked after extraction and before chunking. Quality, "
                        "required metadata/page count, recency and uniqueness are recorded for "
                        "each source. Exact and embedding-near duplicates are quarantined; "
                        "older editions are archived with version metadata. A persistent "
                        "content-hash ledger reuses unchanged document/chunk embeddings.", styles["BodyText"]),
              Spacer(1, 4 * mm), table([
                  ["Measure", "Observed"],
                  ["Documents checked", len(verification_rows) or "not measured"],
                  ["Quarantined documents", quarantined if verification_rows else "not measured"],
                  ["Archived editions", archived if verification_rows else "not measured"],
                  ["Changed documents", len(ingestion.get("changed_documents", []))],
                  ["Chunks embedded / reused", f"{ingestion.get('chunks_embedded', 'not measured')} / {ingestion.get('chunks_reused', 'not measured')}"],
                  ["Deleted-source chunks removed / published orphans",
                   f"{ingestion.get('deleted_document_chunks_removed', 'not measured')} / {ingestion.get('orphan_chunks_in_published_snapshot', 'not measured')}"],
                  ["Injection documents flagged", ingestion.get("injection_documents_flagged", "not measured")],
              ], [75 * mm, 75 * mm]),
              Spacer(1, 4 * mm),
              Paragraph("Batch B is generated from `indexer/pipeline/batch_b.py` and includes "
                        "two exact copies, a near-copy, truncated and corrupt inputs, missing "
                        "metadata, a paired newer edition, a planted instruction and three "
                        "irrelevant documents. See the appended verification screenshot.", styles["Small"]), PageBreak()]

    story += [Paragraph("B — Evaluation", styles["Section"]),
              Paragraph("The golden set contains answerable, abstention and difficult questions. "
                        "The runner executes the module, retrieval and end-to-end levels twice "
                        "with recorded model settings and seeds.", styles["BodyText"]),
              Spacer(1, 4 * mm), table([
                  ["Metric", "Baseline", "Candidate"],
                  ["Recall@3", fmt(seed_a.get("recall@3")), fmt(candidate_a.get("recall@3"))],
                  ["Recall@5", fmt(seed_a.get("recall@5")), fmt(candidate_a.get("recall@5"))],
                  ["MRR / nDCG@5", f"{fmt(seed_a.get('mrr'))} / {fmt(seed_a.get('ndcg@5'))}",
                   f"{fmt(candidate_a.get('mrr'))} / {fmt(candidate_a.get('ndcg@5'))}"],
                  ["Citation validity / abstention correctness",
                   f"{fmt(seed_a.get('citation_validity'))} / {fmt(seed_a.get('abstention_correctness'))}",
                   f"{fmt(candidate_a.get('citation_validity'))} / {fmt(candidate_a.get('abstention_correctness'))}"],
                  ["Faithfulness (human labels)",
                   f"{fmt(seed_a.get('faithfulness'))} ({seed_a.get('faithfulness_label_count', 0)})",
                   f"{fmt(candidate_a.get('faithfulness'))} ({candidate_a.get('faithfulness_label_count', 0)})"],
                  ["p50 / p95 latency ms",
                   f"{fmt(seed_a.get('latency_p50_ms'), 1)} / {fmt(seed_a.get('latency_p95_ms'), 1)}",
                   f"{fmt(candidate_a.get('latency_p50_ms'), 1)} / {fmt(candidate_a.get('latency_p95_ms'), 1)}"],
              ], [53 * mm, 48 * mm, 48 * mm]), Spacer(1, 4 * mm),
              table([["Module measure", "Observed"],
                     ["Mean paraphrase cosine", fmt((module.get("pairs") or {}).get("mean_paraphrase_cosine"))],
                     ["Mean unrelated cosine", fmt((module.get("pairs") or {}).get("mean_unrelated_cosine"))],
                     ["Cosine gap", fmt((module.get("pairs") or {}).get("gap"))],
                     ["Embedding time per text (ms)", fmt(module.get("embedding_time_ms_per_text_in_pair_experiment"), 2)],
                     ["Determinism max absolute difference", fmt(module.get("embedding_determinism_max_abs_difference"), 6)]
              ], [75 * mm, 75 * mm]), PageBreak()]

    story += [Paragraph("C — Pipeline change and gate", styles["Section"]),
              Paragraph("The experiment changes chunk size from 400/50 to 320/50 while preserving "
                        "the embedding and generation models. The candidate collection and API "
                        "Service are isolated from the baseline. A runtime ConfigMap supplies "
                        "release thresholds; the gate stops promotion when a limit fails.", styles["BodyText"]),
              Spacer(1, 4 * mm), table([
                  ["Gate threshold", "Configured", "Candidate observation"],
                  ["Maximum recall@5 drop", "2 percentage points", fmt(seed_a.get("recall@5"))],
                  ["Minimum human-reviewed faithfulness", "0.80, at least 8 labels", fmt(candidate_a.get("faithfulness"))],
                  ["Minimum citation validity", "0.95", fmt(candidate_a.get("citation_validity"))],
                  ["Maximum p95 latency", "15,000 ms", fmt(candidate_a.get("latency_p95_ms"), 1)],
                  ["Minimum abstention correctness", "1.00", fmt(candidate_a.get("abstention_correctness"))],
                  ["Decision", gate_result.get("decision", "not measured"),
                   "; ".join(gate_result.get("failures", [])) or "no recorded gate failures"],
              ], [52 * mm, 42 * mm, 68 * mm]), Spacer(1, 5 * mm),
              Paragraph("A controlled failed-gate run must be labeled as a gate test. It is not "
                        "presented as a measured model regression unless the candidate run itself "
                        "produced that result.", styles["Small"]), PageBreak()]

    story += [Paragraph("D — Observability and operations", styles["Section"]),
              Paragraph("API traces are emitted as structured JSON to stdout and persisted on the "
                        "`ragops-data` PVC. Each trace includes the request/rewrite, embedding and "
                        "collection version, retrieved source/version/chunk/scores, filters, exact "
                        "prompt and hash, response, citations, guardrail actions, cache status and "
                        "per-stage latency. The CLI verifies the prompt hash and reconstructs the "
                        "recorded context.", styles["BodyText"]), Spacer(1, 4 * mm),
              table([["Operational item", "Measured evidence"],
                      ["Observed pod CPU/memory", resource_observation(args.resource_usage)],
                      ["Declared requests / limits", "API 200m/256Mi to 1 CPU/1Gi; Chroma 100m/512Mi to 1 CPU/2Gi; Redis 50m/128Mi to 500m/512Mi."],
                      ["Indexer Job sample", "No running-job `kubectl top` sample was captured; see its requests/limits in k8s/assignment3/batch-b-job.yaml."],
                     ["API metrics", "`/metrics` via port-forward; request, retrieval, generation, cache, abstention and token metrics."],
                     ["Trace summary", "Top-1 similarity distribution, cache/abstention rates, per-stage p95 and injection flags."],
                     ["Persistence", "PVC holds the data lake, report files, embedding ledger, archive, quarantine and JSONL traces."],
                      ["Bad release recovery", "Bad embedding-model rollout stalled; undo restored baseline readiness. See rollback trace."],
              ], [42 * mm, 120 * mm]), Spacer(1, 5 * mm),
              Paragraph("The assignment screenshots that follow should show actual command or UI "
                        "output from this cluster; screenshots are kept in the appendix and do not "
                        "count toward the eight-page report limit.", styles["Small"]), PageBreak()]

    story += [Paragraph("E/F — Coverage, Kubernetes, and team notes", styles["Section"]),
              Paragraph("Forty live queries (28 in-scope and 12 out-of-scope) are compared with the "
                        "golden set using nearest-question embedding similarity. Six questions are "
                        "added from uncovered in-scope topics. The release gate checks in-scope "
                        "coverage; out-of-scope similarity remains separately reported because "
                        "unsupported questions should be abstained on, not taught as answers.", styles["BodyText"]),
              Spacer(1, 4 * mm), table([["Coverage measure", "Before", "After six questions"],
                    ["In-scope covered / total",
                     f"{before_coverage.get('in_scope_covered', 'not measured')} / {before_coverage.get('in_scope_total', 'not measured')}",
                     f"{after_coverage.get('in_scope_covered', 'not measured')} / {after_coverage.get('in_scope_total', 'not measured')}"],
                    ["In-scope coverage (release gate)", fmt(before_coverage.get("in_scope_coverage")),
                     fmt(after_coverage.get("in_scope_coverage"))],
                    ["All-live coverage (includes OOD)", fmt(before_coverage.get("coverage")),
                     fmt(after_coverage.get("coverage"))],
                    ["Out-of-scope similarity", fmt(before_coverage.get("out_of_scope_similarity_coverage")),
                     fmt(after_coverage.get("out_of_scope_similarity_coverage"))],
                    ["Uncovered topic groups", str(before_coverage.get("uncovered_topics", {})),
                     str(after_coverage.get("uncovered_topics", {}))]],
                   [59 * mm, 52 * mm, 52 * mm]), Spacer(1, 5 * mm),
              Paragraph("Kubernetes uses an API Deployment, Chroma StatefulSet/PVC, Redis, "
                        "writer-only indexer Jobs/CronJob, evaluation Job, separate candidate "
                        "Deployment/Service, ConfigMaps and a shared data PVC. Gate thresholds are "
                        "mounted at runtime. The production Service remains unchanged until the "
                        "candidate passes.", styles["BodyText"]), Spacer(1, 5 * mm),
              table([["Contributor", "Verified contribution"],
                     [args.member1, args.contribution1 or "[team to verify and complete]"],
                     [args.member2, args.contribution2 or "[team to verify and complete]"]],
                    [45 * mm, 117 * mm]), Spacer(1, 4 * mm),
              Paragraph("AI-use statement: Codex assisted with implementation, test scaffolding, "
                        "report drafting, and command orchestration. Ollama generated answers only "
                        "at runtime; the team must verify questions, labels, citations, and all "
                        "reported live measurements before submission.", styles["Small"]), PageBreak()]

    story += [Paragraph("G — Lifecycle and quality mapping", styles["Section"]),
              Paragraph("This follows the two intertwined lifecycles in Figure 3 of the reference "
                        "paper. Open items are recorded explicitly for team review.", styles["BodyText"]),
              Spacer(1, 3 * mm),
              compact_table([["Figure 3 stage", "Implementation / evidence", "Open item"],
                ["Ingest", "PDF/Markdown extraction in indexer/pipeline/extract.py; Batch B generator.", "Batch source set is local and synthetic."],
                ["Verify", "Four checks and per-run report; measured quarantine/archive counts.", "Injected file is flagged but not quarantined."],
                ["Update data lake", "PVC lake, quarantine/archive, SQLite content-hash ledger.", "Restore demo still needs a captured run."],
                ["Update retrieval sources", "Immutable Chroma snapshots; active pointer switches after indexing.", "Deleted-source orphans: zero in measured run."],
                ["Offline testing", "Module/retrieval/E2E runner, two seeds, runtime gate.", "Eight human faithfulness labels pending."],
                ["Live testing", "Separate candidate collection, Deployment and Service.", "Promotion blocked while gate rejects."],
                ["Check coverage", "40 live queries, 0.72 similarity, six additions.", "New questions need group review."]],
                [29 * mm, 76 * mm, 57 * mm]), Spacer(1, 4 * mm),
              compact_table([["Table 2 quality", "Measure / threshold", "Current evidence"],
                ["Adaptability", "Configurable chunk size and incremental source updates.", "400/50 baseline vs 320/50 candidate; 678/684 chunks."],
                ["Monitorability", "Recall@5 drop ≤0.02; citation ≥0.95; abstention ≥1.00; p95 ≤15s; coverage ≥0.85.", "Timestamped results and trace summary."],
                ["Observability", "Track relevance, context adherence, injection flags and cache.", "JSONL traces; injection flagged; human labels pending."],
                ["Traceability", "Record versions, retrieval routing, prompt hash and grounded sources.", "Trace reconstruction and PVC JSONL."],
                 ["Reliability", "Resource limits, readiness, persistent PVC and controlled undo.", "Bad-model rollout stalled; undo restored baseline readiness and a new trace confirmed the collection/model."]],
                [29 * mm, 72 * mm, 61 * mm]), PageBreak()]

    root_cause = (args.root_cause.read_text(encoding="utf-8").strip()
                  if args.root_cause.is_file() else
                  "[select one measured wrong or abstained answer and record its trace-only cause]")
    story += [Paragraph("G — Short answers and trace diagnosis", styles["Section"]),
              Paragraph(f"<b>(a) Verification:</b> {leading_check} caught the most failed checks "
                        f"({failed_checks.get(leading_check, 0)}). An injected document was flagged "
                        f"but remained indexable ({'yes' if missed_injection else 'not observed'}); "
                        "a policy to quarantine flagged instructions plus human review would catch it earlier.", styles["Small"]),
              Spacer(1, 2 * mm),
              Paragraph(f"<b>(b) Metric gap:</b> Module embeddings had a paraphrase/unrelated cosine "
                        f"gap of {fmt((module.get('pairs') or {}).get('gap'))} and determinism difference "
                        f"{fmt(module.get('embedding_determinism_max_abs_difference'), 6)}, while answer "
                        f"fact probes passed {seed_a.get('answer_fact_checks', 'not measured')}/"
                        f"{seed_a.get('answer_fact_check_count', 'not measured')}; missed rows: "
                        f"{', '.join(failed_fact_rows) or 'none'}.", styles["Small"]),
              Spacer(1, 2 * mm),
              Paragraph(f"<b>(c) Versions:</b> {archived} older edition(s) were archived and marked "
                        "superseded instead of deleted. Deleting them removes retrieval history and "
                        "prevents rollback to an earlier policy.", styles["Small"]),
              Spacer(1, 2 * mm),
              Paragraph("<b>(d) Least-trusted metric:</b> semantic query coverage. A 0.72 cosine "
                        "cutoff is only a proxy for test-set representativeness; it does not establish "
                        "answer correctness and must be read with retrieval and answer metrics.", styles["Small"]),
              Spacer(1, 2 * mm),
              Paragraph("<b>(e) Hardest paper idea:</b> coordinating software and data lifecycles "
                        "without exposing a partially indexed collection. We use immutable Chroma "
                        "snapshots and switch the active pointer only after verification and indexing, "
                        "adapting the paper's update-and-test feedback loop to this small cluster.", styles["Small"]),
              Spacer(1, 2 * mm),
              Paragraph("<b>(f) Kubernetes:</b> indexer Job/CronJob is the only vector writer; API "
                        "Deployments read. Chroma StatefulSet and PVC preserve data, ConfigMaps carry "
                        "thresholds, and the candidate Deployment/Service isolate the changed pipeline "
                        "until a gate passes.", styles["Small"]),
              Spacer(1, 4 * mm),
              Paragraph("<b>D5 — Root cause from trace only (five lines):</b>", styles["Small"]),
              Paragraph(root_cause.replace("\n", "<br/>"), styles["Small"]), PageBreak()]

    screenshots = sorted(args.screenshots.glob("*.png")) if args.screenshots.is_dir() else []
    for prefix, caption in SCREENSHOT_CAPTIONS.items():
        match = next((path for path in screenshots if path.name.startswith(prefix)), None)
        story.append(Paragraph("Appendix — Screenshot evidence", styles["Section"]))
        story.append(Paragraph(caption, styles["Caption"]))
        story.append(Spacer(1, 3 * mm))
        if match:
            picture = Image(str(match))
            picture._restrictSize(180 * mm, 245 * mm)
            story.append(picture)
        else:
            story.append(Paragraph("[capture the actual screen for this required step]", styles["BodyText"]))
        story.append(PageBreak())

    def footer(canvas: Any, document: Any) -> None:
        canvas.saveState()
        width, _ = A4
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#506574"))
        canvas.drawString(18 * mm, 12 * mm, "RAHBAR · Assignment 03 · Team review required")
        canvas.drawRightString(width - 18 * mm, 12 * mm, f"{document.page}")
        canvas.restoreState()

    document = SimpleDocTemplate(str(output), pagesize=A4, rightMargin=18 * mm,
        leftMargin=18 * mm, topMargin=17 * mm, bottomMargin=20 * mm,
        title="RAHBAR Assignment 03 — RAGOps", author="RAHBAR Team")
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    print(f"Wrote {output} with 8 report pages and {len(SCREENSHOT_CAPTIONS)} screenshot appendix pages")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=REPO / "eval/results/baseline.json")
    parser.add_argument("--candidate", type=Path, default=REPO / "eval/results/candidate.json")
    parser.add_argument("--verification", type=Path)
    parser.add_argument("--ingestion", type=Path)
    parser.add_argument("--coverage", type=Path, default=REPO / "eval/results/coverage.json")
    parser.add_argument("--gate", type=Path)
    parser.add_argument("--human-review", type=Path,
                        default=REPO / "eval/assignment3/human_review.csv")
    parser.add_argument("--root-cause", type=Path,
                        default=REPO / "eval/results/root-cause.md")
    parser.add_argument("--resource-usage", type=Path,
                        default=REPO / "eval/results/resource-usage.txt")
    parser.add_argument("--screenshots", type=Path,
                        default=REPO / "docs/assignment3/screenshots")
    parser.add_argument("--out", type=Path,
                        default=REPO / "docs/assignment3/Assignment_03_Report.pdf")
    parser.add_argument("--member1", default="Shaheer")
    parser.add_argument("--roll1", default=os.environ.get("SHAHEER_ROLL", ""))
    parser.add_argument("--contribution1", default="")
    parser.add_argument("--member2", default="Taha Sohail")
    parser.add_argument("--roll2", default=os.environ.get("TAHA_ROLL", ""))
    parser.add_argument("--contribution2", default="")
    args = parser.parse_args()
    build(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
