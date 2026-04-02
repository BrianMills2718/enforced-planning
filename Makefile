## enforced-planning — framework for enforced planning, context gating, doc-code alignment

.PHONY: help test test-quick check lint

help:  ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | awk -F ':.*##' '{printf "%-20s %s\n", $$1, $$2}'

test:  ## Run full test suite
	python -m pytest tests/ -v

test-quick:  ## Run tests with minimal output
	python -m pytest tests/ -q

check: lint test-quick  ## Run lint + tests

lint:  ## Run ruff linter
	ruff check scripts/ tests/ --ignore=F401
