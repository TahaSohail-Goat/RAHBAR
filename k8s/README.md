# Kubernetes setup for Assignment 3

The repo's base manifests provide the API, Chroma, Redis, UI, network policies,
runtime configuration, and the `ragops-data` PVC. The Assignment 3 manifests add
the Batch B index Job, baseline/evaluation Jobs, and the isolated candidate API.
Run commands from the repository root inside WSL.

## Fresh local cluster

```bash
export MINIKUBE_HOME=/mnt/d/SCD-Tools/minikube-assignment3
export KUBECONFIG=/mnt/d/SCD-Tools/kube/config-wsl
make cluster PROFILE=rahbar-a3-wsl
make deploy-real PROFILE=rahbar-a3-wsl TAG=dev
make ragops-image PROFILE=rahbar-a3-wsl TAG=dev
kubectl apply -k k8s/base
kubectl apply -f k8s/assignment3/baseline-job.yaml
kubectl apply -f k8s/assignment3/batch-b-job.yaml
kubectl apply -f k8s/assignment3/candidate.yaml
```

`make deploy-real` fetches the pinned corpus, configures the WSL-to-Ollama egress
address, builds the API/indexer/UI images, and deploys the base overlay. Ollama
must expose `nomic-embed-text` and `llama3.2:3b`. Keep real credentials out of
these manifests; add hosted-provider credentials only through a Kubernetes Secret.

## Run and inspect the Jobs

```bash
make ragops-batch-b
kubectl -n rahbar wait --for=condition=complete job/batch-b-index --timeout=30m
kubectl -n rahbar logs job/batch-b-index
make ragops-baseline-job
kubectl -n rahbar wait --for=condition=complete job/ragops-baseline --timeout=60m
make ragops-candidate
kubectl -n rahbar wait --for=condition=complete job/candidate-index --timeout=30m
kubectl -n rahbar rollout status deployment/api-candidate
make ragops-eval-job
kubectl -n rahbar logs job/ragops-eval
make ragops-gate-job
kubectl -n rahbar logs job/ragops-gate-check
kubectl -n rahbar get all,pvc,configmap,cronjob,job
```

The Jobs require network access to Chroma, Redis, and the locally hosted Ollama
endpoint. PVC-backed data, verification reports, embedding ledger, archives,
quarantine, traces, and results survive pod restarts. The indexer Job/CronJob is
the only vector-store writer; API and candidate API Deployments are readers.

## Runtime gate and rollback

`ragops-gates` is mounted into the evaluation and gate-check Jobs at
`/etc/rahbar/gates/gate.yaml`. Changing its data does not rebuild the image. Delete
and reapply `ragops-gate-check` after changing a threshold, compare its failure
list, then restore the committed value before normal use. Do not relax a threshold
solely to manufacture a passing decision. Release the candidate only after the
real evaluation and required human labels pass. After a rollback demo,
confirm the restored Deployment is ready and emit a trace that names the prior
collection/model.

```bash
kubectl -n rahbar edit configmap ragops-gates
kubectl -n rahbar rollout history deployment/api
kubectl -n rahbar rollout undo deployment/api
kubectl -n rahbar rollout status deployment/api
kubectl -n rahbar port-forward service/api 8000:8000
curl -fsS http://127.0.0.1:8000/readyz
curl -fsS http://127.0.0.1:8000/metrics
```

The report's screenshot appendix must use uncropped terminal captures from the
team's cluster. Keep the cluster output, trace samples, and measured JSON results
under `eval/results/` and `traces/`.
