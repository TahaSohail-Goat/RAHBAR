# Assignment 03: RAGOps implementation and runbook

This maps the Assignment 03 PDF rubric to the repository and gives the local and
Kubernetes run commands. Run shell commands from the repository root, inside WSL
on Windows.

## Implemented components

| Area | Implementation | Evidence |
| --- | --- | --- |
| A. Data management | `indexer/pipeline/verification.py` checks extraction quality, metadata/page completeness, recency, byte duplicates, and embedding near-duplicates before chunking. Failed files are quarantined; older versions are archived. `EmbeddingLedger` persists document/chunk vectors by content hash and model. | `reports/verification-*.json`, `reports/ingestion-*.json`, SQLite embedding ledger, quarantine/archive folders on the PVC. |
| B. Evaluation | `eval/assignment3/prepare_dataset.py` generates 25 golden questions, 40 live queries, 15 paraphrase pairs, 15 unrelated pairs, and review sheets. `runner.py` measures embedding separation/determinism/time, recall@3/@5, MRR, nDCG@5, citation validity, abstention correctness, latency, typo stress, cache behavior, query coverage, and seed-to-seed deltas. | Timestamped `eval/results/run-*.json`; reviewers complete the human review CSVs before faithfulness is reported. |
| C. Pipeline/gate | Candidate changes chunk size from 400/50 to 320/50. `gate.py` reads `gate.yaml` at runtime and checks recall@5 regression, human-labeled faithfulness, citations, abstention, p95, and query coverage. The candidate has its own collection, Deployment, and Service. | Gate JSON reports release/reject and exact failures. |
| D. Observability | Every API query writes a structured trace to stdout and `/var/lib/rahbar/traces/queries.jsonl`, including retrieval context, document version, model/collection, filters, prompt/hash, response/citations, guardrails, latency, and cache status. | `python -m eval.assignment3.trace TRACE_ID --file ...` verifies prompt hash and reconstructs context. `trace_summary` computes time-window metrics. |
| E. Coverage/drift | `coverage.py` compares 40 live queries to the golden set, groups uncovered topics, and checks the increase after six questions are added. Batch B includes exact/near duplicates, malformed files, missing metadata, a newer edition, an injected instruction, and three noise documents. | `eval/results/coverage.json`; verification/ingestion reports and a second suite run. |
| F. Kubernetes | The API, indexer Job/CronJob, evaluation Job, candidate API, Chroma/Redis, ConfigMaps, and `ragops-data` PVC are in `k8s/`. Network policies allow required model/vector/cache paths. | Kubernetes job logs/status, rollout history, PVC-backed traces/reports. |

## Dataset and human review

Generate the datasets (the command preserves existing human-review entries):

```bash
make ragops-data
```

`eval/golden.jsonl` has 25 questions: 20 answerable, five abstention questions,
and at least five difficult questions. Authoring metadata is intentionally
honest: Assignment 2 questions are marked for group authorship verification and
Assignment 3 additions are marked as AI drafts that need group review. The team
must identify at least eight questions it actually wrote and review at least
eight synthetic questions in `eval/assignment3/human_review.csv` before claiming
those rubric counts. Do not mark a question human-written or reviewed before a
teammate has done that work.

The evaluator creates `eval/results/reviews/faithfulness_review.csv` with eight
answer/trace pairs. Two teammates should label whether each answer is supported
by its evidence, enter reviewer names/notes, and rerun the evaluation/gate. Until
eight labels exist, the runtime gate fails closed.

## Baseline, Batch B, and candidate run

1. Install and start Docker, Minikube, kubectl, and Ollama as described in the
   repository README. Ollama must provide `nomic-embed-text` and `llama3.2:3b`.
2. Prepare datasets and run static/offline checks:

   ```bash
   make ragops-data
   make test
   make lint
   make check
   ```

3. Deploy the real corpus and wait for readiness:

   ```bash
   export MINIKUBE_HOME=/mnt/d/SCD-Tools/minikube-assignment3
   export KUBECONFIG=/mnt/d/SCD-Tools/kube/config-wsl
   make deploy-real TAG=dev PROFILE=rahbar-a3-wsl
   kubectl -n rahbar get pods,svc,pvc,jobs
   kubectl -n rahbar rollout status deployment/api
   ```

   API/indexer share the `ragops-data` PVC. The initial indexer copies its image
   corpus to `/var/lib/rahbar/lake`; reports, archive, quarantine, embedding
   ledger, evaluation results, and traces persist on the PVC.

4. Run Batch B through verification/chunk/embed/store:

   ```bash
   make ragops-batch-b
   kubectl -n rahbar wait --for=condition=complete job/batch-b-index --timeout=30m
   kubectl -n rahbar logs job/batch-b-index
   ```

   Inspect the newest verification and ingestion JSON on the PVC. Confirm exact
   and near duplicates, malformed files, the injected document, changed/reused
   chunk counts, zero deleted-document orphans, and archived newer-version
   behavior. For the unchanged-run proof, delete only the completed Job object,
   apply `batch-b-job.yaml` again without changing the corpus, and confirm the
   new ingestion report says `chunks_embedded: 0` and all chunks reused.

5. Build the evaluation image and capture a same-dataset live baseline:

   ```bash
   make ragops-image TAG=dev
   make ragops-baseline-job
   kubectl -n rahbar wait --for=condition=complete job/ragops-baseline --timeout=60m
   kubectl -n rahbar logs job/ragops-baseline
   ```

   The Job uses the `app=ragops-eval` NetworkPolicy label and the shared PVC.
   Evaluation queries the live model and services and can take several minutes.
   It records two seeded passes, module/retrieval/E2E metrics, typo stress,
   repeated-query cache behavior, coverage, and eight manual-review prompts. The
   result is `/var/lib/rahbar/results/baseline.json`.

6. Build the alternate chunk-size index and its separate API. The index Job
   publishes `rahbar-candidate`; its reader is `api-candidate:8000`.

   ```bash
   make ragops-candidate
   kubectl -n rahbar wait --for=condition=complete job/candidate-index --timeout=30m
   kubectl -n rahbar rollout status deployment/api-candidate
   kubectl -n rahbar port-forward svc/api-candidate 8001:8000
   ```

   In another terminal verify `http://127.0.0.1:8001/readyz`, then run the same
   evaluator with `--collection rahbar-candidate` and save the candidate JSON.
   Compare it with the baseline using:

   ```bash
   make ragops-gate CANDIDATE=/var/lib/rahbar/results/candidate.json \
     BASELINE=/var/lib/rahbar/results/baseline.json
   ```

7. Demonstrate a rejected and a passing gate. For a fail, use a separate copied
   candidate JSON with recall@5 below the configured allowance or p95 above its
   limit; retain the nonzero exit and failure report. A pass requires the real
   candidate result and completed human review. If a threshold change is
   justified, edit the runtime ConfigMap and record the reason:

   ```bash
   kubectl -n rahbar edit configmap ragops-gates
   ```

   The `ragops-gate-check` Job evaluates the latest saved candidate result against
   the mounted ConfigMap without repeating the full suite. Delete and recreate
   that Job after a ConfigMap edit to show that the failure list changes without
   rebuilding the image. Restore the committed thresholds afterward. The pass
   demonstration still requires eight genuine human labels and must not be
   fabricated.

   The next Job reads the ConfigMap without rebuilding an image. Do not loosen a
   threshold just to manufacture a pass.

## Kubernetes metrics, traces, and rollback

```bash
kubectl -n rahbar get jobs,pods,pvc
kubectl -n rahbar logs job/batch-b-index
kubectl -n rahbar logs job/candidate-index
kubectl -n rahbar port-forward svc/api 8000:8000
curl -fsS http://127.0.0.1:8000/metrics
```

Traces go to API stdout and the PVC. Copy them, then reconstruct any request and
summarize a time window:

```bash
kubectl -n rahbar cp POD_NAME:/var/lib/rahbar/traces/queries.jsonl docs/evidence/queries.jsonl
python -m eval.assignment3.trace TRACE_ID --file docs/evidence/queries.jsonl
python -m eval.assignment3.trace_summary --file docs/evidence/queries.jsonl
```

Keep an unsafe candidate isolated; the release gate must stop promotion. For the
rollback demonstration, capture `kubectl rollout history deployment/api`, run
`kubectl -n rahbar rollout undo deployment/api`, and wait for readiness. The
query trace captures the active collection/model so the recovered version can
be identified. Metrics include top-1 similarity distribution, abstention/cache
rates, per-stage p95, and injected-document flags in `trace_summary`.

## Report and screenshots

The PDF report must be at most eight pages, with screenshots in an appendix that
does not count toward the limit. Put both members' names and roll numbers on page
one; include metric/gate tables, contributor split, and a 2–3-line AI-use
statement. Capture actual output for these six areas:

1. Verification checks and Batch B quarantine/archive results.
2. Golden/evaluation metrics and manual-review step.
3. Rejected and passing candidate gate.
4. Query trace/prompt reconstruction and metrics endpoint.
5. Live coverage before/after and uncovered-topic groups.
6. Kubernetes PVC/jobs/candidate Service and promotion/rollback behavior.

Capture the actual terminal, browser, or Kubernetes screen after running the
commands; do not submit fabricated terminal content. Roll numbers, group-written
question claims, and subjective human labels need teammate verification. The
source intentionally leaves those review actions explicit rather than inventing
identity or claiming work that was not performed.

The report builder reserves eight main pages and creates one appendix page per
required screenshot. It includes the Figure 3 lifecycle mapping, five Table 2
qualities, six short answers, and the five-line trace-only diagnosis. The eleven
appendix captures are A1 verification, A2 incremental ingestion, B3 evaluation,
C2 rejected gate, C2 passing gate, D1 trace, D2 reconstruction, E2/E4 coverage,
F1/F2 cluster state, F2 Job logs, and F3/F5 threshold/rollback/resources. A
passing-gate capture must wait for genuine human labels and a real passing run.
