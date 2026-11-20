"""Reconstruct the context and prompt for one persisted query trace."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace_id")
    parser.add_argument("--file", type=Path, default=Path("/var/lib/rahbar/traces/queries.jsonl"))
    args = parser.parse_args()
    for line in args.file.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("trace_id") == args.trace_id:
            prompt = record.get("prompt", "")
            digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest() if prompt else None
            if record.get("prompt_sha256") and record["prompt_sha256"] != digest:
                raise SystemExit("trace prompt hash verification failed")
            print(json.dumps({"trace_id": args.trace_id, "user_query": record.get("user_query"),
                              "rewritten_query": record.get("rewritten_query"),
                              "retrieved_context": record.get("retrieved"), "prompt": prompt,
                              "prompt_sha256": digest, "response": record.get("response")},
                             indent=2, ensure_ascii=False))
            return 0
    raise SystemExit(f"trace id not found: {args.trace_id}")


if __name__ == "__main__":
    raise SystemExit(main())
