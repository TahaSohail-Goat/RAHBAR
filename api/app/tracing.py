"""Per-query trace records: structured stdout plus a durable JSONL copy."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

trace_context: ContextVar[dict[str, Any] | None] = ContextVar("rahbar_trace", default=None)
_write_lock = threading.Lock()
_log = logging.getLogger("rahbar.trace")


def update_trace(**fields: Any) -> None:
    context = trace_context.get()
    if context is not None:
        context.update(fields)


def append_trace(field: str, value: Any) -> None:
    context = trace_context.get()
    if context is not None:
        context.setdefault(field, []).append(value)


def cached_trace_snapshot() -> dict[str, Any]:
    """Return only request-independent context needed to explain a cache hit."""
    context = trace_context.get() or {}
    return {key: context[key] for key in (
        "rewritten_query", "collection", "collection_version", "retrieved", "filters",
        "reranked_order", "prompt", "model", "model_parameters", "guardrail_actions",
        "stage_latency_ms", "latency_ms",
    ) if key in context}


def finalize_trace(question: str, response: Any, settings: Any) -> dict[str, Any]:
    context = trace_context.get() or {}
    prompt = context.get("prompt", "")
    actions = list(context.get("guardrail_actions", []))
    if context.get("rewritten_query", question) != question:
        actions.append("instruction-like preamble removed before retrieval and generation")
    record = {
        "schema_version": 1,
        "trace_id": context.get("trace_id", response.request_id),
        "timestamp": context.get("timestamp", datetime.now(timezone.utc).isoformat()),
        "user_query": question,
        "rewritten_query": context.get("rewritten_query", question),
        "embedding_model": settings.embed_model,
        "collection": context.get("collection", settings.collection),
        "collection_version": context.get("collection_version"),
        "retrieved": context.get("retrieved", []),
        "filters": context.get("filters", []),
        "reranked_order": context.get("reranked_order", []),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest() if prompt else None,
        "prompt": prompt,
        "model": settings.llm_model,
        "model_parameters": {"temperature": settings.temperature, "seed": settings.llm_seed},
        "response": response.answer,
        "citations": [item.model_dump(mode="json") for item in response.citations],
        "answered_from_context": response.answered_from_context,
        "guardrail_actions": actions,
        "cache": context.get("cache_status", "skipped"),
        "stage_latency_ms": context.get("stage_latency_ms", {}),
        "latency_ms": context.get("latency_ms"),
        "injection_attempts_flagged": int(bool(actions)),
        "trace_reconstructed_from_cache": bool(context.get("trace_reconstructed_from_cache")),
    }
    root = Path(os.environ.get("RAGOPS_DATA_DIR", "/var/lib/rahbar")) / "traces"
    try:
        root.mkdir(parents=True, exist_ok=True)
        with _write_lock, (root / "queries.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        _log.info("query trace", extra={"trace": record})
    except OSError as exc:
        _log.error("trace persistence failed", extra={"trace_id": record["trace_id"],
                                                        "error": type(exc).__name__})
        # stdout remains the operational fallback, even if the PVC is unavailable.
        _log.info("query trace", extra={"trace": record})
    return record
