# 1. This tells Make to run the 'help' target if someone just types 'make'
.DEFAULT_GOAL := help

.PHONY: check lint typecheck typecheck-cold typecheck-stop help deploy-dev deploy-test-build deploy-test deploy-test-stop

check: lint typecheck ## Run lint and type checks

lint: ## Run Ruff linting
	ruff check . --fix

typecheck: ## Run mypy through the faster daemon
	dmypy run -- src/cn3s

typecheck-cold: ## Run mypy without the daemon
	mypy --cache-dir .mypy_cache/cold src/cn3s

typecheck-stop: ## Stop the mypy daemon
	dmypy stop

# SHC web app. IIS always proxies to http://127.0.0.1:8000/{R:0}, so the dev server and the
# standalone container both use host port 8000 and cannot run at the same time.
SHC_PORT ?= 8000
SHC_COMPOSE = docker compose -f web/compose.yaml
export SHC_DURATION_CURVES_HOST_DIR ?= /mnt/e/OneDrive/OneDrive - Agência Nacional de Águas/data/CN3S/Exceedance
# Exit 0 when something accepts TCP connections on 127.0.0.1:$(SHC_PORT).
SHC_PORT_BUSY = python3 -c "import socket,sys; s=socket.socket(); s.settimeout(1); sys.exit(s.connect_ex(('127.0.0.1',$(SHC_PORT))))"

deploy-dev: ## Run SHC dev server (Gunicorn --reload) on :8000; run inside the devcontainer
	@if $(SHC_PORT_BUSY); then \
		echo "ERROR: port $(SHC_PORT) is already in use (dev server or test container?)."; \
		echo "       Stop it first, e.g. 'make deploy-test-stop' on the host, then retry."; exit 1; fi
	PYTHONPATH=src python -m gunicorn --reload --workers 1 --bind 0.0.0.0:$(SHC_PORT) web.app:app

deploy-test-build: ## Build the standalone SHC image (first use or source changes)
	$(SHC_COMPOSE) build web

deploy-test: ## Start standalone SHC using the existing local image
	@command -v docker >/dev/null || { echo "ERROR: docker not found. Run this on the host/WSL, not in the devcontainer."; exit 1; }
	@[ -n "$$SHC_DURATION_CURVES_HOST_DIR" ] || { echo "ERROR: set SHC_DURATION_CURVES_HOST_DIR to the HOST path of the Exceedance folder."; exit 1; }
	@[ -d "$$SHC_DURATION_CURVES_HOST_DIR" ] || { echo "ERROR: '$$SHC_DURATION_CURVES_HOST_DIR' is not a directory on this machine (use the host path, not /data)."; exit 1; }
	@SHC_HOST_PORT=$(SHC_PORT) $(SHC_COMPOSE) up -d --no-build --pull never web || { \
		echo "ERROR: could not start SHC. If the image has not been built, run 'make deploy-test-build'."; exit 1; }
	@for i in 1 2 3 4 5 6 7 8 9 10; do \
		code=$$(curl --noproxy '*' --max-time 2 -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$(SHC_PORT)/shc) || code=000; \
		if [ "$$code" = "302" ]; then echo "SHC responding on http://127.0.0.1:$(SHC_PORT)/shc (HTTP $$code)"; exit 0; fi; \
		sleep 2; done; \
	echo "ERROR: SHC did not return HTTP 302 (last status: $$code); see '$(SHC_COMPOSE) logs --tail 100'"; exit 1

deploy-test-stop: ## Stop the standalone SHC container (frees port 8000 for deploy-dev)
	SHC_HOST_PORT=$(SHC_PORT) SHC_DURATION_CURVES_HOST_DIR=$${SHC_DURATION_CURVES_HOST_DIR:-.} $(SHC_COMPOSE) stop

## Display this help screen
help:
	@echo "Available commands:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
