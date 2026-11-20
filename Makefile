# RAHBAR development and evidence commands. Run from a Bash environment.

SHELL := /bin/bash
NS ?= rahbar
TAG ?= dev
PROFILE ?= minikube
PY ?= python3
VENV ?= .venv
BIN := $(abspath $(VENV))/bin
REPORT_LIBS ?= /mnt/d/SCD-Tools/assignment3-report-libs
# The Ingress address. On Linux this is the minikube IP. On macOS or Windows with the
# docker driver, run `minikube tunnel` in another terminal and use INGRESS_IP=127.0.0.1.
INGRESS_IP ?= $(shell minikube -p $(PROFILE) ip 2>/dev/null)
HOST ?= rahbar.local

.DEFAULT_GOAL := help
.PHONY: help install test lint dev cluster images apply secret index ask fetch eval eval-fixtures check deploy-real audit-live calibrate-cache evidence rollout-demo ragops-data ragops-image ragops-suite ragops-coverage ragops-traces ragops-gate ragops-batch-b ragops-candidate ragops-baseline-job ragops-eval-job ragops-gate-job ragops-report

help: ## list the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-14s %s\n", $$1, $$2}'

install: ## create .venv and install the api, indexer and tool dependencies
	$(PY) -m venv $(VENV)
	"$(BIN)/pip" install -q --upgrade pip
	"$(BIN)/pip" install -q -r api/requirements-dev.txt -r indexer/requirements-dev.txt

test: ## run API, indexer and evaluation tests without external services
	cd api && "$(BIN)/pytest" -q
	cd indexer && "$(BIN)/pytest" -q
	"$(BIN)/python" -m pytest -q -c eval/pyproject.toml eval/tests

lint: ## ruff and mypy over everything in Python
	"$(BIN)/ruff" check api indexer eval corpus scripts
	cd api && "$(BIN)/mypy" app
	cd indexer && "$(BIN)/mypy" pipeline

dev: ## run the API with stubs on http://localhost:8000, serving the chat UI too
	cd api && SERVE_UI_DIR=../ui RETRIEVER=stub LLM_PROVIDER=stub "$(BIN)/uvicorn" app.main:app --reload --port 8000

cluster: ## start minikube with Calico, then enable metrics-server and ingress
	minikube start -p $(PROFILE) --driver=docker --cni=calico --memory=6144 --cpus=4
	minikube -p $(PROFILE) addons enable metrics-server
	minikube -p $(PROFILE) addons enable ingress

images: ## build corpus-free images and load them into minikube
	docker build --build-arg VCS_REF=$$(git rev-parse HEAD) -t rahbar-api:$(TAG) api
	docker build --build-arg VCS_REF=$$(git rev-parse HEAD) -t rahbar-indexer:$(TAG) indexer
	docker build --build-arg VCS_REF=$$(git rev-parse HEAD) -t rahbar-ui:$(TAG) ui
	minikube -p $(PROFILE) image load rahbar-api:$(TAG)
	minikube -p $(PROFILE) image load rahbar-indexer:$(TAG)
	minikube -p $(PROFILE) image load rahbar-ui:$(TAG)

apply: ## apply the explicitly stubbed dev overlay
	kubectl apply -k k8s/overlays/dev

secret: ## create the LLM key Secret from the LLM_API_KEY variable; never from a file
	@test -n "$$LLM_API_KEY" || { echo "export LLM_API_KEY=... first"; exit 1; }
	kubectl create secret generic rahbar-secret -n $(NS) \
	  --from-literal=LLM_API_KEY="$$LLM_API_KEY" --dry-run=client -o yaml | kubectl apply -f -

index: ## run the indexer once from the reindex CronJob template
	kubectl create job --from=cronjob/reindex reindex-$$(date +%s) -n $(NS)
	@echo "watch it with: kubectl get jobs -n $(NS) -w"

ask: ## ask through the Ingress: make ask Q="What CGPA puts a student on academic warning?"
	@curl -s -X POST "http://$(INGRESS_IP)/api/ask" -H "Host: $(HOST)" \
	  -H 'Content-Type: application/json' -d "$$(Q="$(Q)" $(PY) -c 'import json,os; print(json.dumps({"question": os.environ["Q"]}))')" \
	  | $(PY) -m json.tool

fetch: ## download the documents listed in corpus/sources.yaml
	"$(BIN)/python" corpus/fetch.py

eval: ## score eval/golden.yaml through the Ingress and apply the CI gate
	"$(BIN)/python" eval/run_eval.py --api "http://$(INGRESS_IP)" --host $(HOST)

eval-fixtures: ## score the local fixtures through the API with offline service doubles
	"$(BIN)/python" -m pytest -q -c eval/pyproject.toml eval/tests/test_fixture_stack.py

check: ## run the submission checker
	$(PY) scripts/check_submission.py

deploy-real: ## fetch pinned PDFs, resolve host egress, build corpus image, and deploy prod
	PYTHON="$(BIN)/python" TAG="$(TAG)" MINIKUBE_PROFILE="$(PROFILE)" bash scripts/deploy_real.sh

audit-live: ## measure three chunk settings and cache thresholds against real local services
	"$(BIN)/python" -m eval.live_audit --out eval/runs/current

calibrate-cache: ## measure labelled cache false hits using the configured real embedding model
	"$(BIN)/python" -m eval.calibrate_cache

evidence: ## capture real cluster/resource evidence (run while the index Job is active)
	bash scripts/capture_evidence.sh

rollout-demo: ## perform a visible UI update and rollback, then restore the original image
	INGRESS_IP="$(INGRESS_IP)" HOST="$(HOST)" bash scripts/rollout_demo.sh

ragops-data: ## generate the Assignment 3 golden/live/embedding datasets
	"$(BIN)/python" eval/assignment3/prepare_dataset.py

ragops-image: ## build the live evaluation image
	docker build -f eval/Dockerfile.ragops -t rahbar-eval:$(TAG) .
	minikube -p $(PROFILE) image load rahbar-eval:$(TAG)

ragops-suite: ## run all three evaluation levels twice and save a timestamped JSON report
	"$(BIN)/python" -m eval.assignment3.runner

ragops-coverage: ## measure 40-query golden coverage before/after the six new questions
	"$(BIN)/python" -m eval.assignment3.coverage

ragops-traces: ## summarize durable query traces for an optional time window
	"$(BIN)/python" -m eval.assignment3.trace_summary $(if $(SINCE),--since "$(SINCE)") $(if $(UNTIL),--until "$(UNTIL)")

ragops-gate: ## compare CANDIDATE and BASELINE result JSON using runtime thresholds
	@test -f "$(CANDIDATE)" -a -f "$(BASELINE)" || { echo 'set CANDIDATE and BASELINE to result JSON paths'; exit 2; }
	"$(BIN)/python" -m eval.assignment3.gate --candidate "$(CANDIDATE)" --baseline "$(BASELINE)"

ragops-batch-b: ## run the planted Batch B ingestion Job in Kubernetes
	kubectl apply -f k8s/assignment3/batch-b-job.yaml

ragops-candidate: ## publish and deploy the alternate chunk-size collection/API
	kubectl apply -f k8s/assignment3/candidate.yaml

ragops-baseline-job: ## capture the fixed-pipeline live baseline on rahbar
	kubectl apply -f k8s/assignment3/baseline-job.yaml

ragops-eval-job: ## launch the persistent-volume evaluation and release-gate Job
	kubectl apply -f k8s/assignment3/eval-job.yaml

ragops-gate-job: ## run the gate against saved results using the mounted runtime ConfigMap
	kubectl apply -f k8s/assignment3/gate-check-job.yaml

ragops-report: ## render the six-page report and screenshot appendix from measured evidence
	PYTHONPATH="$(REPORT_LIBS):$${PYTHONPATH:-}" "$(BIN)/python" docs/assignment3/build_report.py
