# Assignment 3 screenshot evidence

These uncropped, full-desktop PNGs were captured on 2026-11-21 from a separate
maximized Windows PowerShell terminal. The terminal output comes from the local
Minikube cluster or the saved JSON produced by its completed Jobs. The project
cluster was running in the `rahbar-a3-wsl` profile.

| File | Evidence shown |
| --- | --- |
| `A1-verification.png` | Batch B failed checks, quarantines, and archived edition |
| `A2-incremental.png` | Ingestion report: 678 chunks reused, 0 embedded, 0 orphans |
| `B3-evaluation.png` | Measured baseline and candidate evaluation metrics |
| `C2-reject.png` | Live gate Job rejection due to 0 human faithfulness labels |
| `D1-trace.png` | Persisted trace ID, model, collection version, and prompt hash |
| `D2-reconstruct.png` | Trace reconstruction CLI output and verified prompt hash |
| `E2-coverage.png` | Live query coverage before and after six added questions |
| `F1-f2-k8s.png` | Live Deployments, StatefulSet, PVCs, ConfigMaps, CronJob, and Jobs |
| `F2-logs.png` | Completed Batch B indexer Job logs |
| `F2-eval-logs.png` | Completed baseline evaluation Job log tail and Kubernetes Job status |
| `F3-mismatch.png` | API pod at 0/1 and live `/readyz` response naming the model mismatch |
| `F3-f5-release.png` | Runtime gate comparison, restored API readiness, trace, and pod resources |

`C2-pass.png` is intentionally absent. The candidate has not passed the gate; the
team must add eight genuine human faithfulness judgments and rerun evaluation
before capturing that state.
