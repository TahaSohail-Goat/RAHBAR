#!/usr/bin/env bash
# Run from the repository root, after starting host Ollama on 0.0.0.0:11434.
set -euo pipefail
PYTHON=${PYTHON:-python3}
TAG=${TAG:-dev}
MINIKUBE_PROFILE=${MINIKUBE_PROFILE:-minikube}
OLLAMA_URL=${OLLAMA_URL:-http://host.minikube.internal:11434}
command -v docker >/dev/null
command -v minikube >/dev/null
command -v kubectl >/dev/null
"$PYTHON" corpus/fetch.py
"$PYTHON" corpus/fetch.py --verify
make cluster
revision=$(git rev-parse HEAD)
docker build --build-arg "VCS_REF=$revision" -t "rahbar-api:$TAG" api
docker build --build-arg "VCS_REF=$revision" -t "rahbar-ui:$TAG" ui
docker build -t rahbar-indexer:corpus-base indexer
docker build -t "rahbar-indexer:$TAG" -f - corpus/raw <<'DOCKERFILE'
FROM rahbar-indexer:corpus-base
COPY --chown=10001:10001 *.pdf _index.json /corpus/
DOCKERFILE
for image in "rahbar-api:$TAG" "rahbar-ui:$TAG" "rahbar-indexer:$TAG"; do
  minikube -p "$MINIKUBE_PROFILE" image load --overwrite=true "$image"
done
ollama_host=$(OLLAMA_URL="$OLLAMA_URL" "$PYTHON" -c 'import os,urllib.parse; print(urllib.parse.urlsplit(os.environ["OLLAMA_URL"]).hostname)')
ollama_ip=${OLLAMA_IP:-$(minikube -p "$MINIKUBE_PROFILE" ssh -- "getent ahostsv4 '$ollama_host' | head -n 1 | cut -d ' ' -f 1" | tr -d '\r')}
[[ -n "$ollama_ip" ]] || { echo 'Set OLLAMA_IP to the IPv4 address reachable inside Minikube.' >&2; exit 1; }
mkdir -p output/deployment
kubectl kustomize k8s/overlays/prod | "$PYTHON" scripts/configure_deployment.py \
  --ollama-url "$OLLAMA_URL" --ollama-cidr "$ollama_ip/32" \
  --indexer-image "rahbar-indexer:$TAG" --api-image "rahbar-api:$TAG" \
  --ui-image "rahbar-ui:$TAG" > output/deployment/prod.yaml
# Never apply a dev Job template over a real immutable Job template.
kubectl apply -f k8s/base/namespace.yaml
kubectl -n rahbar delete job initial-index --ignore-not-found
kubectl apply -f output/deployment/prod.yaml
deadline=$((SECONDS + 1500))
while ! kubectl -n rahbar wait --for=condition=complete job/initial-index --timeout=5s \
    >/dev/null 2>&1; do
  failed=$(kubectl -n rahbar get job initial-index \
    -o jsonpath='{.status.conditions[?(@.type=="Failed")].status}')
  if [[ "$failed" == "True" ]]; then
    kubectl -n rahbar logs job/initial-index --all-containers=true || true
    kubectl -n rahbar describe job initial-index || true
    exit 1
  fi
  if (( SECONDS >= deadline )); then
    echo 'Timed out waiting for the initial index job.' >&2
    kubectl -n rahbar logs job/initial-index --all-containers=true || true
    exit 1
  fi
done
kubectl -n rahbar rollout restart deployment/api
kubectl -n rahbar rollout status deployment/api --timeout=300s
kubectl -n rahbar get pods,svc,ingress,hpa
echo 'Use minikube tunnel on Windows/macOS Docker drivers, then ask through rahbar.local.'
