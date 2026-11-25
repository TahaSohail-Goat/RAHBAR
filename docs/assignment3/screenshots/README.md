# Assignment 3 screenshot evidence

These uncropped, full-desktop PNGs were captured from the local Minikube cluster or from JSON saved by its completed Jobs. The original evidence was captured on 2026-11-21 in a maximized Windows PowerShell terminal. `C2-pass.png` was captured on 2026-11-25 in a maximized Windows Terminal console after the live evaluation Job completed.

| File | Evidence shown |
| --- | --- |
| `A1-verification.png` | Batch B failed checks, quarantines, and archived edition |
| `A2-incremental.png` | Ingestion report: 678 chunks reused, 0 embedded, 0 orphans |
| `B3-evaluation.png` | Measured baseline and candidate evaluation metrics |
| `C2-reject.png` | Live gate Job rejection due to 0 human faithfulness labels |
| `C2-pass.png` | Live gate Job release with 8 completed human faithfulness judgments |
| `D1-trace.png` | Persisted trace ID, model, collection version, and prompt hash |
| `D2-reconstruct.png` | Trace reconstruction CLI output and verified prompt hash |
| `E2-coverage.png` | Live query coverage before and after six added questions |
| `F1-f2-k8s.png` | Live Deployments, StatefulSet, PVCs, ConfigMaps, CronJob, and Jobs |
| `F2-logs.png` | Completed Batch B indexer Job logs |
| `F2-eval-logs.png` | Completed baseline evaluation Job log tail and Kubernetes Job status |
| `F3-mismatch.png` | API pod at 0/1 and live `/readyz` response naming the model mismatch |
| `F3-f5-release.png` | Runtime gate comparison, restored API readiness, trace, and pod resources |

The passing evaluation used the recorded 8/8 human faithfulness labels. The separate answer-fact probe passed 9 of 12 checks; the report retains the missed-answer count rather than treating the faithfulness labels as a substitute for answer-quality review.
