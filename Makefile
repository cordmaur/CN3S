# 1. This tells Make to run the 'help' target if someone just types 'make'
.DEFAULT_GOAL := help

.PHONY: check lint typecheck typecheck-cold typecheck-stop help

check: lint typecheck ## Run lint and type checks

lint: ## Run Ruff linting
	ruff check . --fix

typecheck: ## Run mypy through the faster daemon
	dmypy run -- src/cn3s

typecheck-cold: ## Run mypy without the daemon
	mypy --cache-dir .mypy_cache/cold src/cn3s

typecheck-stop: ## Stop the mypy daemon
	dmypy stop

## Display this help screen
help:
	@echo "Available commands:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'
