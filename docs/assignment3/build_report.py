"""Build the Assignment 3 report PDF from measured JSON and real screenshots."""

from __future__ import annotations

import argparse
import csv
import json
import os
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
    "01-data": "A — pre-chunking verification, Batch B quarantine and archive report",
    "02-evaluation": "B — golden evaluation summary and human-review worksheet",
    "03-gate": "C — candidate gate rejection and passing release decision",
    "04-traces": "D — persisted query trace, reconstructed prompt and metrics endpoint",
    "05-coverage": "E — live-query coverage before/after expansion and uncovered groups",
    "06-kubernetes": "F — Kubernetes PVC, jobs, candidate Service and rollback state",
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


def load_review_counts(path: Path) -> tuple[int, int]:
    if not path.is_file():
        return 0, 0
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    authored = sum(bool(row.get("human_authored_by_group_member", "").strip()) for row in rows)
    reviewed = sum(bool(row.get("synthetic_question_reviewed_by_group_member", "").strip())
                   for row in rows)
    return authored, reviewed


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

    # Main report: six deliberately bounded pages. Screenshots follow as appendix.
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
                     ["Indexer resources", "Capture `kubectl top pod` while the Batch B Job runs."],
                     ["API metrics", "`/metrics` via port-forward; request, retrieval, generation, cache, abstention and token metrics."],
                     ["Trace summary", "Top-1 similarity distribution, cache/abstention rates, per-stage p95 and injection flags."],
                     ["Persistence", "PVC holds the data lake, report files, embedding ledger, archive, quarantine and JSONL traces."],
                     ["Bad release recovery", "Gate refusal and/or rollout undo followed by readiness verification."],
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
    print(f"Wrote {output} with 6 report pages and {len(SCREENSHOT_CAPTIONS)} screenshot appendix pages")


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
