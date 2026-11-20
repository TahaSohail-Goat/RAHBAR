"""Helpers for using the verified corpus in module-level measurements."""

from __future__ import annotations

import json
import os
from pathlib import Path

from indexer.pipeline.config import IndexerSettings


def verified_corpus_sources(settings: IndexerSettings) -> set[str] | None:
    """Use the latest verifier allow-list so quarantined inputs aren't extracted again."""
    data_dir = Path(os.environ.get("RAGOPS_DATA_DIR", str(Path(settings.corpus_dir) / ".ragops")))
    reports = sorted((data_dir / "reports").glob("verification-*.json"))
    if not reports:
        return None
    report = json.loads(reports[-1].read_text(encoding="utf-8"))
    return {row["source"] for row in report.get("documents", [])
            if not row.get("quarantined", False)}
