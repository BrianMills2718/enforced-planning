## enforced-planning — framework for enforced planning, context gating, doc-code alignment

.PHONY: help test test-quick check lint infer check-deps check-caps migrate-rels verify-couplings review-surfaces plan-registry status

REPO ?= .
SCAN_DIR ?= ~/projects

help:  ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | awk -F ':.*##' '{printf "%-20s %s\n", $$1, $$2}'

test:  ## Run full test suite
	python -m pytest tests/ -v

test-quick:  ## Run tests with minimal output
	python -m pytest tests/ -q

check: lint test-quick  ## Run lint + tests

lint:  ## Run ruff linter
	ruff check scripts/ tests/ --ignore=F401

## --- Relationships V2 tools ---

infer:  ## Infer dependency graph for a repo (REPO=path)
	python scripts/infer_dependencies.py $(REPO)

check-deps:  ## Validate plan dependency references (REPO=path to plans dir)
	python scripts/check_plan_deps.py $(REPO)/docs/plans/ --scan-dir $(SCAN_DIR)

check-caps:  ## Validate plan Capabilities sections (REPO=path to plans dir)
	python scripts/check_plan_capabilities.py $(REPO)/docs/plans/

migrate-rels:  ## Migrate relationships.yaml V1→V2 (REPO=path)
	python scripts/migrate_relationships.py $(REPO)/relationships.yaml --dry-run

## --- Agent verification protocol (Plan #11) ---

verify-couplings:  ## Verify validated couplings via LLM agent (REPO=path, COMMIT=sha)
	@echo "Verifying validated couplings in $(REPO)"
	@python scripts/verify_coupling.py --help

review-surfaces:  ## Run LLM semantic review of truth surfaces (REPO=path)
	python scripts/review_truth_surfaces.py --repo $(REPO)

## --- Phase 6: Cross-repo governance ---

plan-registry:  ## Build cross-repo plan registry (SCAN_DIR=~/projects)
	python scripts/build_plan_registry.py --scan-dir $(SCAN_DIR) --output generated/plan_registry.json --summary

ecosystem-deps:  ## Build ecosystem cross-repo dependency map from generated/inferred_*.json
	python scripts/build_ecosystem_dep_map.py --output generated/ecosystem_dep_map.json --summary

infer-all:  ## Infer deps across all governed repos in SCAN_DIR (writes generated/inferred_*.json)
	@for repo in $$(ls -d $(SCAN_DIR)/*/); do \
	  name=$$(basename $$repo); \
	  if [ -f "$$repo/meta-process.yaml" ]; then \
	    echo "Inferring $$name ..."; \
	    python scripts/infer_dependencies.py $$repo --output generated/inferred_$$name.json; \
	  fi; \
	done

status:  ## Git status
	@git status --short --branch
