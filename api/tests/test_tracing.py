import json

from app.schemas import AskResponse
from app.tracing import finalize_trace, trace_context
from app.config import Settings


def test_finalized_trace_persists_reconstructable_prompt_and_context(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("RAGOPS_DATA_DIR", str(tmp_path))
    token = trace_context.set({
        "trace_id": "trace-123", "timestamp": "2026-11-21T00:00:00Z",
        "prompt": '{"messages":[{"role":"user","content":"question"}]}',
        "retrieved": [{"chunk_id": "c1", "text": "source text"}],
        "collection": "rahbar", "collection_version": "generation-1",
        "stage_latency_ms": {"retrieval_ms": 12.3}, "cache_status": "miss",
    })
    response = AskResponse(request_id="trace-123", answer="answer", citations=[],
                           answered_from_context=True, confidence="high", retrieved=[],
                           provider="ollama")

    try:
        record = finalize_trace("question", response, Settings())
    finally:
        trace_context.reset(token)

    saved = json.loads((tmp_path / "traces" / "queries.jsonl").read_text().splitlines()[0])
    assert record["prompt"] == saved["prompt"]
    assert record["retrieved"][0]["text"] == "source text"
    assert record["collection_version"] == "generation-1"
    assert saved["cache"] == "miss"
