from pathlib import Path

from pipeline.models import Document, Page
from pipeline.run import prepare
from pipeline.verification import EmbeddingLedger, verify_documents


def test_quality_completeness_exact_and_near_duplicate_flags(tmp_path: Path) -> None:
    contents = {
        "canonical.md": "common exact body",
        "exact-copy.md": "common exact body",
        "near-copy.md": "similar body",
        "missing.md": "missing fields",
    }
    paths = {name: tmp_path / name for name in contents}
    for name, text in contents.items():
        paths[name].write_text(text, encoding="utf-8")
    documents = [Document(name, "2026", False, [Page(name, 1, text)])
                 for name, text in contents.items()]
    metadata = {name: {"name": name, "doc_version": "2026", "pages": 1,
                       "logical_id": name} for name in contents if name != "missing.md"}
    vectors = [[1.0, 0.0], [1.0, 0.0], [0.99, 0.01], [0.0, 1.0]]

    valid, report = verify_documents(documents, paths, metadata, embeddings=vectors,
                                     near_duplicate_threshold=0.94)

    rows = {row["source"]: row for row in report["documents"]}
    assert rows["canonical.md"]["quarantined"] is False
    assert "exact duplicate" in rows["exact-copy.md"]["checks"]["uniqueness"]["reasons"][0]
    assert "near-duplicate" in rows["near-copy.md"]["checks"]["uniqueness"]["reasons"][0]
    assert "missing title" in rows["missing.md"]["checks"]["completeness"]["reasons"]
    assert [document.source for document in valid] == ["canonical.md"]


def test_embedding_ledger_reuses_vectors_and_tracks_deleted_documents(tmp_path: Path) -> None:
    ledger = EmbeddingLedger(tmp_path / "ledger.sqlite3", "fixture-model")
    try:
        assert ledger.get("chunk-1", "unchanged") is None
        assert ledger.get_document_embedding("doc.md", "body") is None
        ledger.put("chunk-1", "unchanged", [0.2, 0.8])
        ledger.put_document_embedding("doc.md", "body", [0.4, 0.6])
        ledger.save_documents([{"source": "doc.md", "sha256": "abc", "doc_version": "2026",
                               "quarantined": False}])
        assert ledger.get("chunk-1", "unchanged") == [0.2, 0.8]
        assert ledger.get_document_embedding("doc.md", "body") == [0.4, 0.6]
        assert ledger.document_hashes() == {"doc.md": "abc"}
        ledger.save_documents([])
        assert ledger.document_hashes() == {}
    finally:
        ledger.close()


def test_unreadable_old_version_is_quarantined_without_breaking_version_checks(
    tmp_path: Path,
) -> None:
    current_path = tmp_path / "policy-2027.md"
    old_path = tmp_path / "policy-2026.pdf"
    current_path.write_text("Current policy text", encoding="utf-8")
    old_path.write_bytes(b"unreadable PDF")
    current = Document("policy-2027.md", "2027", False,
                       [Page("policy-2027.md", 1, "Current policy text")])
    metadata = {
        "policy-2027.md": {"name": "Policy", "doc_version": "2027", "pages": 1,
                           "logical_id": "policy"},
        "policy-2026.pdf": {"name": "Policy", "doc_version": "2026", "pages": 1,
                           "logical_id": "policy"},
    }

    valid, report = verify_documents(
        [current], {current.source: current_path, "policy-2026.pdf": old_path}, metadata,
        embeddings=[[1.0, 0.0]], extraction_failures={"policy-2026.pdf": "corrupt PDF"},
    )

    rows = {row["source"]: row for row in report["documents"]}
    assert [document.source for document in valid] == ["policy-2027.md"]
    assert rows["policy-2027.md"]["archived"] is False
    assert rows["policy-2026.pdf"]["quarantined"] is True


def test_prepare_uses_verifier_allow_list_before_extracting_sources(tmp_path: Path) -> None:
    good = tmp_path / "good.md"
    good.write_text("---\nname: Good\ndoc_version: 2026\npages: 1\n---\n\nReadable text.",
                    encoding="utf-8")
    (tmp_path / "quarantined.pdf").write_bytes(b"corrupt PDF")

    documents = prepare(str(tmp_path), allowed_sources={"good.md"})

    assert [document.source for document in documents] == ["good.md"]
