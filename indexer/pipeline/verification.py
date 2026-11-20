"""RAGOps document verification and incremental embedding bookkeeping.

Verification runs after extraction and before chunking. Every document receives
four explicit checks; rejected files are quarantined, while superseded editions
are archived and retained with their metadata so an operator can roll back.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .models import Document


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return -1.0
    dot = sum(a * b for a, b in zip(left, right))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return dot / norm if norm else -1.0


def _version(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", value)) or (0,)


def verify_documents(
    documents: list[Document], paths: dict[str, Path], metadata: dict[str, dict],
    *, embeddings: list[list[float]] | None = None, near_duplicate_threshold: float = 0.94,
    extraction_failures: dict[str, str] | None = None,
) -> tuple[list[Document], dict]:
    """Return indexable documents and a complete per-document verification report."""
    records: list[dict] = []
    hashes: dict[str, list[int]] = defaultdict(list)
    for i, doc in enumerate(documents):
        path = paths[doc.source]
        raw = path.read_bytes()
        text = "\n".join(page.text for page in doc.pages)
        expected = metadata.get(doc.source, {})
        bad_chars = sum(text.count(ch) for ch in ("\ufffd", "\x00"))
        quality_reasons = []
        if not text.strip():
            quality_reasons.append("no readable text after extraction/OCR")
        if text and bad_chars / max(1, len(text)) > 0.01:
            quality_reasons.append(f"garbled text: {bad_chars} replacement/control characters")
        if doc.pages and sum(bool(page.text.strip()) for page in doc.pages) / len(doc.pages) < 0.25:
            quality_reasons.append("fewer than 25% of pages yielded readable text")
        completeness_reasons = []
        title = expected.get("name") or expected.get("title") or ""
        version = expected.get("doc_version") or doc.doc_version
        expected_pages = expected.get("pages")
        if not title:
            completeness_reasons.append("missing title")
        if not version or version == "unknown":
            completeness_reasons.append("missing date/version metadata")
        if not len(doc.pages):
            completeness_reasons.append("missing page count")
        if expected_pages is None:
            completeness_reasons.append("missing page-count metadata")
            expected_page_count = None
        else:
            try:
                expected_page_count = int(expected_pages)
                if expected_page_count < 1:
                    raise ValueError
            except (TypeError, ValueError):
                expected_page_count = None
                completeness_reasons.append(f"invalid page-count metadata: {expected_pages!r}")
        if expected_page_count is not None and expected_page_count != len(doc.pages):
            completeness_reasons.append(
                f"page count mismatch: metadata={expected_page_count}, extracted={len(doc.pages)}")
        # A PDF that fails its parser or has a page-count mismatch is treated as truncated.
        if (path.suffix.lower() == ".pdf" and expected_page_count is not None
                and expected_page_count != len(doc.pages)):
            completeness_reasons.append("possible truncated or corrupt PDF")
        digest = hashlib.sha256(raw).hexdigest()
        hashes[digest].append(i)
        records.append({
            "source": doc.source, "title": str(title), "doc_version": str(version),
            "page_count": len(doc.pages), "sha256": digest,
            "injection_attempts": int(bool(re.search(
                r"\b(ignore|disregard|override|reveal|system prompt)\b", text, re.I))),
            "checks": {
                "quality": {"passed": not quality_reasons, "reasons": quality_reasons or [
                    "readable extraction; no material garbling detected"]},
                "completeness": {"passed": not completeness_reasons,
                                 "reasons": completeness_reasons or [
                                     "source, title, version, page count and extraction are present"]},
                "recency": {"passed": True, "reasons": []},
                "uniqueness": {"passed": True, "reasons": []},
            },
            "quarantined": False, "archived": False,
        })

    for source, reason in (extraction_failures or {}).items():
        records.append({
            "source": source, "title": metadata.get(source, {}).get("name", Path(source).stem),
            "doc_version": metadata.get(source, {}).get("doc_version", "unknown"),
            "page_count": 0, "sha256": hashlib.sha256(paths[source].read_bytes()).hexdigest(),
            "checks": {
                "quality": {"passed": False, "reasons": [f"extraction failed: {reason}"]},
                "completeness": {"passed": False, "reasons": ["page count and extracted text unavailable"]},
                "recency": {"passed": True, "reasons": ["recency could not be compared after extraction failure"]},
                "uniqueness": {"passed": True, "reasons": ["no duplicate match was established"]},
            }, "quarantined": True, "archived": False,
            "quarantine_reason": ["quality", "completeness"],
        })

    # Exact byte duplicates are deterministic and need no model call.
    for indexes in hashes.values():
        if len(indexes) > 1:
            for duplicate in indexes[1:]:
                records[duplicate]["checks"]["uniqueness"] = {
                    "passed": False,
                    "reasons": [f"exact duplicate of {records[indexes[0]]['source']}"],
                }

    # Embedding similarity catches near duplicates without relying on filenames.
    if embeddings is not None:
        # Extraction failures are appended after the successful documents above
        # and therefore have no corresponding embedding vector.
        for i in range(len(documents)):
            if not records[i]["checks"]["uniqueness"]["passed"]:
                continue
            for j in range(i):
                if records[j]["checks"]["uniqueness"]["passed"] and _cosine(
                        embeddings[i], embeddings[j]) >= near_duplicate_threshold:
                    records[i]["checks"]["uniqueness"] = {
                        "passed": False,
                        "reasons": [f"near-duplicate of {records[j]['source']} "
                                    f"(cosine >= {near_duplicate_threshold:.3f})"],
                    }
                    break

    # Recency is a positive verification when the edition is current or its
    # superseded status is explicit; it is not a reason to quarantine old policy.
    groups: dict[str, list[int]] = defaultdict(list)
    # Extraction failures were appended after the successful Document records.
    # They must not affect version selection or index the shorter documents list.
    for i, record in enumerate(records[:len(documents)]):
        logical_id = str(metadata.get(record["source"], {}).get("logical_id") or
                         re.sub(r"\b(?:19|20)\d{2}(?:[-_]\d{1,2})?\b", "", record["title"],
                                flags=re.I).casefold())
        logical_id = re.sub(r"[-_]", " ", logical_id)
        logical_id = re.sub(r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
                            r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|"
                            r"nov(?:ember)?|dec(?:ember)?)\b", "", logical_id, flags=re.I)
        groups[" ".join(logical_id.split())].append(i)
    for indexes in groups.values():
        newest = max((records[i]["doc_version"] for i in indexes), key=_version)
        for i in indexes:
            is_old = _version(records[i]["doc_version"]) < _version(newest)
            marked = bool(metadata.get(records[i]["source"], {}).get("superseded", False))
            passed = True
            records[i]["checks"]["recency"] = {
                "passed": passed,
                "reasons": ([f"newer version {newest} detected; older edition marked superseded and archived"]
                            if is_old else
                            ["edition is explicitly marked superseded and will be archived"]
                            if marked else ["current version or no newer matching edition detected"]),
            }
            records[i]["archived"] = is_old and marked
        if is_old:
            records[i]["archived"] = True
            documents[i].superseded = True

    indexable: list[Document] = []
    for i, doc in enumerate(documents):
        failed = [name for name, check in records[i]["checks"].items() if not check["passed"]]
        records[i]["quarantined"] = bool(failed)
        if failed:
            records[i]["quarantine_reason"] = failed
        else:
            indexable.append(doc)

    return indexable, {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "checks": ["quality", "completeness", "recency", "uniqueness"],
        "near_duplicate_threshold": near_duplicate_threshold,
        "documents": records,
    }


class EmbeddingLedger:
    """Persistent chunk embedding cache; unchanged chunk text is never re-embedded."""

    def __init__(self, database: Path, model: str) -> None:
        database.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(database)
        self.connection.execute("""CREATE TABLE IF NOT EXISTS embeddings (
            model TEXT NOT NULL, chunk_id TEXT NOT NULL, text_sha256 TEXT NOT NULL,
            vector_json TEXT NOT NULL, PRIMARY KEY(model, chunk_id, text_sha256))""")
        self.connection.execute("""CREATE TABLE IF NOT EXISTS document_state (
            source TEXT PRIMARY KEY, sha256 TEXT NOT NULL, doc_version TEXT NOT NULL)""")
        self.connection.execute("""CREATE TABLE IF NOT EXISTS document_embeddings (
            model TEXT NOT NULL, source TEXT NOT NULL, text_sha256 TEXT NOT NULL,
            vector_json TEXT NOT NULL, PRIMARY KEY(model, source, text_sha256))""")
        self.model = model

    def get(self, chunk_id: str, text: str) -> list[float] | None:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        row = self.connection.execute(
            "SELECT vector_json FROM embeddings WHERE model=? AND chunk_id=? AND text_sha256=?",
            (self.model, chunk_id, digest),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, chunk_id: str, text: str, vector: list[float]) -> None:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        self.connection.execute(
            "INSERT OR REPLACE INTO embeddings VALUES(?,?,?,?)",
            (self.model, chunk_id, digest, json.dumps(vector, separators=(",", ":"))),
        )

    def get_document_embedding(self, source: str, text: str) -> list[float] | None:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        row = self.connection.execute(
            "SELECT vector_json FROM document_embeddings WHERE model=? AND source=? AND text_sha256=?",
            (self.model, source, digest),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def put_document_embedding(self, source: str, text: str, vector: list[float]) -> None:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        self.connection.execute(
            "INSERT OR REPLACE INTO document_embeddings VALUES(?,?,?,?)",
            (self.model, source, digest, json.dumps(vector, separators=(",", ":"))),
        )
        self.connection.commit()

    def document_hashes(self) -> dict[str, str]:
        return dict(self.connection.execute("SELECT source, sha256 FROM document_state"))

    def save_documents(self, records: list[dict]) -> None:
        self.connection.execute("DELETE FROM document_state")
        self.connection.executemany(
            "INSERT OR REPLACE INTO document_state VALUES(?,?,?)",
            [(row["source"], row["sha256"], row["doc_version"]) for row in records
             if not row["quarantined"]],
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()


def preserve_documents(report: dict, paths: dict[str, Path], state_dir: Path) -> None:
    """Copy failed and superseded source files to durable quarantine/archive folders."""
    for record in report["documents"]:
        if record["quarantined"]:
            target = state_dir / "quarantine" / record["source"]
        elif record["archived"]:
            target = state_dir / "archive" / Path(record["source"]).stem / record["doc_version"] / record["source"]
        else:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if paths[record["source"]].exists():
            shutil.copy2(paths[record["source"]], target)
