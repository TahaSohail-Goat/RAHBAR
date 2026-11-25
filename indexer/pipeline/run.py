"""The indexer Job's entry point. It runs once and exits (section 4.2).

    python -m pipeline.run --dummy    # week 1: three fake chunks, no model needed
    python -m pipeline.run            # the real pipeline: extract, clean, chunk, embed, store

Exit code 0 means the index was written; anything else fails the Job, and
Kubernetes retries it up to the Job's backoffLimit.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

from .config import IndexerSettings, get_settings
from .models import Chunk, Document


def log(msg: str, **fields: object) -> None:
    print(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      "logger": "rahbar.indexer", "request_id": "indexer-" +
                      os.environ.get("HOSTNAME", "local"), "msg": msg, **fields}), flush=True)


class JsonHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        log(record.getMessage(), level=record.levelname,
            error=logging.Formatter().formatException(record.exc_info) if record.exc_info else None)


def _front_matter(path: Path) -> dict[str, str]:
    """Read `key: value` lines between leading '---' markers (used by eval/fixtures)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    meta: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta


def discover(corpus_dir: str) -> list[tuple[Path, str, bool]]:
    """List (path, doc_version, superseded) for every document to index.

    corpus/fetch.py writes _index.json next to the files it downloads; use it when
    present. Otherwise read Markdown front matter (the CI fixtures work this way).
    """
    root = Path(corpus_dir)
    resolved_root = root.resolve()
    index = root / "_index.json"
    found: list[tuple[Path, str, bool]] = []
    indexed: set[Path] = set()
    if index.exists():
        entries = json.loads(index.read_text(encoding="utf-8"))
        corpus_files = {candidate.relative_to(root).as_posix(): candidate.resolve()
                        for candidate in root.rglob("*") if candidate.is_file()}
        manifest_entries = {}
        for entry in entries:
            relative = entry.get("file")
            if not isinstance(relative, str):
                continue
            relative_path = Path(relative)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                continue
            manifest_entries[relative_path.as_posix()] = entry
        for relative, path in corpus_files.items():
            entry = manifest_entries.get(relative)
            if entry is None:
                continue
            if path.is_relative_to(resolved_root):
                found.append((path, str(entry.get("doc_version", "unknown")),
                              bool(entry.get("superseded", False))))
                indexed.add(path)
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.resolve() in indexed:
            continue
        if any(part in {"quarantine", "archive", ".git"} for part in path.relative_to(root).parts):
            continue
        if path.suffix.lower() not in {".pdf", ".md", ".txt"}:
            continue
        if path.name.lower().startswith("readme") or path.name == "_index.json":
            continue
        meta = _front_matter(path) if path.suffix.lower() == ".md" else {}
        found.append((path, meta.get("doc_version", "unknown"),
                      meta.get("superseded", "false").lower() == "true"))
    return found


def prepare(corpus_dir: str, *, allowed_sources: set[str] | None = None) -> list[Document]:
    from .clean import clean
    from .extract import extract

    sources = discover(corpus_dir)
    if allowed_sources is not None:
        sources = [item for item in sources if item[0].name in allowed_sources]
    if not sources:
        raise ValueError(f"no documents found in {corpus_dir}")
    documents = []
    for path, doc_version, superseded in sources:
        doc = clean(extract(str(path), doc_version, superseded))
        readable = sum(bool(p.text) for p in doc.pages)
        if not readable:
            raise ValueError(f"{path.name}: no readable pages after cleaning")
        log("extracted", source=path.name, pages=len(doc.pages),
            ocr_pages=sum(p.ocr for p in doc.pages),
            empty_pages=[p.page for p in doc.pages if not p.text])
        documents.append(doc)
    return documents


def build_chunks(documents: list[Document], size: int, overlap: int) -> list[Chunk]:
    from .chunk import chunk

    chunks = [piece for doc in documents for piece in chunk(doc, size, overlap)]
    original_words = sum(len(p.text.split()) for doc in documents for p in doc.pages)
    stored_words = sum(len(c.text.split()) for c in chunks)
    log("chunked", size=size, overlap=overlap, chunks=len(chunks), original_words=original_words,
        stored_words=stored_words, amplification=round(stored_words / original_words, 4))
    return chunks


def run_pipeline(settings: IndexerSettings) -> int:
    from .embed import embed
    from .store import store
    from .clean import clean
    from .extract import extract
    from .verification import EmbeddingLedger, preserve_documents, verify_documents

    root = Path(settings.corpus_dir)
    discovered = discover(settings.corpus_dir)
    metadata: dict[str, dict] = {}
    index_file = root / "_index.json"
    if index_file.exists():
        metadata.update({item["file"]: item for item in json.loads(index_file.read_text(
            encoding="utf-8"))})
    sources: dict[str, Path] = {}
    versions: dict[str, tuple[str, bool]] = {}
    for path, version, superseded in discovered:
        key = path.name
        sources[key] = path
        versions[key] = (version, superseded)
        if key not in metadata:
            metadata[key] = _front_matter(path) if path.suffix.lower() == ".md" else {}
            metadata[key].setdefault("doc_version", version)
            metadata[key].setdefault("superseded", superseded)
        if "pages" not in metadata[key] and "page_count" in metadata[key]:
            metadata[key]["pages"] = metadata[key]["page_count"]

    documents: list[Document] = []
    extraction_failures: dict[str, str] = {}
    for source, path in sources.items():
        version, superseded = versions[source]
        try:
            documents.append(clean(extract(str(path), version, superseded)))
        except Exception as exc:
            extraction_failures[source] = f"{type(exc).__name__}: {exc}"
            logging.exception("document extraction failed: %s", source)

    state_dir = Path(os.environ.get("RAGOPS_DATA_DIR", str(root / ".ragops")))
    state_dir.mkdir(parents=True, exist_ok=True)
    ledger = EmbeddingLedger(state_dir / "embedding-ledger.sqlite3", settings.embed_model)
    # Reuse document-level duplicate-check embeddings too. A fully unchanged
    # corpus therefore makes no embedding calls after its first verified run.
    samples = [" ".join(page.text for page in doc.pages)[:12000] for doc in documents]
    document_vectors: list[list[float] | None] = [
        ledger.get_document_embedding(doc.source, sample)
        for doc, sample in zip(documents, samples, strict=True)]
    missing_docs = [i for i, vector in enumerate(document_vectors) if vector is None]
    computed_docs = embed([samples[i] for i in missing_docs], settings) if missing_docs else []
    for i, computed_vector in zip(missing_docs, computed_docs, strict=True):
        document_vectors[i] = computed_vector
        ledger.put_document_embedding(documents[i].source, samples[i], computed_vector)
    complete_vectors: list[list[float]] = []
    for cached_vector in document_vectors:
        if cached_vector is None:
            raise RuntimeError("document embedding ledger failed to provide a vector")
        complete_vectors.append(cached_vector)
    document_vectors_ready = complete_vectors
    valid, report = verify_documents(
        documents, sources, metadata, embeddings=document_vectors_ready,
        extraction_failures=extraction_failures,
    )
    preserve_documents(report, sources, state_dir)
    report_dir = state_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    report_path = report_dir / f"verification-{stamp}.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    log("verification finished", report=str(report_path), documents=len(report["documents"]),
        quarantined=sum(item["quarantined"] for item in report["documents"]))
    if not valid:
        raise ValueError("verification quarantined every document; refusing to publish an empty index")

    chunks = build_chunks(valid, settings.chunk_size, settings.chunk_overlap)
    try:
        prior_documents = ledger.document_hashes()
        current_records = [item for item in report["documents"] if not item["quarantined"]]
        current_documents = {item["source"]: item["sha256"] for item in current_records}
        deleted = sorted(set(prior_documents) - set(current_documents))
        changed = sorted(source for source, digest in current_documents.items()
                         if prior_documents.get(source) != digest)
        vectors: list[list[float] | None] = [ledger.get(chunk.id, chunk.text) for chunk in chunks]
        missing_indexes = [i for i, vector in enumerate(vectors) if vector is None]
        missing_vectors = embed([chunks[i].text for i in missing_indexes], settings) if missing_indexes else []
        for i, vector in zip(missing_indexes, missing_vectors):
            vectors[i] = vector
            ledger.put(chunks[i].id, chunks[i].text, vector)
        if any(vector is None for vector in vectors):
            raise RuntimeError("embedding ledger failed to provide a vector for each chunk")
        import redis
        from .store import get_client
        client = get_client(settings)
        redis_client = redis.Redis(host=settings.redis_host, port=settings.redis_port,
                                   decode_responses=True, socket_connect_timeout=5,
                                   socket_timeout=5)
        active_name = redis_client.get(f"rahbar:index:{settings.collection}:active") or settings.collection
        redis_client.close()
        from chromadb.errors import NotFoundError
        try:
            collection = client.get_collection(active_name)
        except NotFoundError:
            deleted_counts = {source: 0 for source in deleted}
        else:
            deleted_counts = {source: len(collection.get(
                where={"source": source}, include=["metadatas"])["ids"]) for source in deleted}
        total = store(chunks, [vector for vector in vectors if vector is not None], settings)
        ledger.save_documents(current_records)
        run_report = {
            "schema_version": 1, "run_id": stamp, "index_count": total,
            "documents": len(current_documents), "changed_documents": changed,
            "deleted_documents": deleted, "chunks_embedded": len(missing_indexes),
            "chunks_reused": len(chunks) - len(missing_indexes),
            "document_duplicate_check_embeddings_computed": len(missing_docs),
            "document_duplicate_check_embeddings_reused": len(documents) - len(missing_docs),
            "deleted_document_chunks_removed": sum(deleted_counts.values()),
            "orphan_chunks_in_published_snapshot": sum(chunk.source in deleted for chunk in chunks),
            "deleted_document_chunk_counts": deleted_counts,
            "injection_documents_flagged": sum(item.get("injection_attempts", 0)
                                                for item in report["documents"]),
            "verification_report": str(report_path),
            "documents_by_source": {source: sum(c.source == source for c in chunks)
                                    for source in sorted(current_documents)},
        }
        (report_dir / f"ingestion-{stamp}.json").write_text(
            json.dumps(run_report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    finally:
        ledger.close()
    log("incremental ingestion finished", **run_report)
    return total


def _plan_pair(value: str) -> tuple[int, int]:
    try:
        size, overlap = map(int, value.split(":"))
        if not 0 <= overlap < size:
            raise ValueError
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected SIZE:OVERLAP with 0 <= OVERLAP < SIZE") from exc
    return size, overlap


def main() -> int:
    logging.basicConfig(level=logging.INFO, handlers=[JsonHandler()], force=True)
    parser = argparse.ArgumentParser(description="Build the RAHBAR index, then exit.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dummy", action="store_true", help="write three fake chunks")
    mode.add_argument("--plan", nargs="+", type=_plan_pair, metavar="SIZE:OVERLAP",
                      help="measure chunk counts and amplification without services")
    mode.add_argument("--batch-b", action="store_true",
                      help="create the reproducible Assignment 3 Batch B before indexing")
    args = parser.parse_args()
    settings = get_settings()
    log("indexer starting", dummy=args.dummy, embed_model=settings.embed_model,
        collection=settings.collection, chroma=f"{settings.chroma_host}:{settings.chroma_port}",
        pod=os.environ.get("HOSTNAME", "-"))
    started = time.perf_counter()
    try:
        if args.plan:
            documents = prepare(settings.corpus_dir)
            for size, overlap in args.plan:
                build_chunks(documents, size, overlap)
            return 0
        if args.batch_b:
            from .batch_b import create_batch
            created = create_batch(Path(settings.corpus_dir) / "batch-b")
            log("batch B prepared", documents=len(created), directory="batch-b")
        if args.dummy:
            from .dummy import write_dummy_index
            from .store import get_client

            count = write_dummy_index(settings, get_client(settings))
            # The dummy writer is only for development. Reset any previously
            # published production pointer when switching an existing dev cluster.
            import redis
            cache = redis.Redis(host=settings.redis_host, port=settings.redis_port,
                                socket_connect_timeout=5, socket_timeout=5)
            with cache.pipeline(transaction=True) as transaction:
                transaction.delete(f"rahbar:index:{settings.collection}:active")
                transaction.incr("rahbar:index_generation")
                transaction.execute()
            cache.close()
        else:
            count = run_pipeline(settings)
    except Exception as exc:
        logging.exception("indexer failed: %s: %s", type(exc).__name__, exc)
        return 1
    log("indexer finished", chunks=count, seconds=round(time.perf_counter() - started, 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
