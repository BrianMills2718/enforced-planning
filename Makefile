## enforced-planning — framework for enforced planning, context gating, doc-code alignment

.PHONY: help test test-quick check lint infer check-deps check-caps migrate-rels verify-couplings review-surfaces promote plan-registry status

REPO ?= .
SCAN_DIR ?= ~/projects
TRUTH_CONFIG ?= $(REPO)/scripts/truth_surface_drift.yaml
SEMANTIC_REVIEW_JSON ?= $(REPO)/docs/ops/semantic_truth_surface_review.json
SEMANTIC_REVIEW_HISTORY ?= $(REPO)/docs/ops/semantic_truth_surface_review_history.json

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

review-surfaces:  ## Run canonical semantic review of truth surfaces (TRUTH_CONFIG=path)
	python scripts/review_truth_surface_semantic.py --config $(TRUTH_CONFIG) --output-json $(SEMANTIC_REVIEW_JSON) --history-json $(SEMANTIC_REVIEW_HISTORY)

promote:  ## Show promotion candidates from semantic review findings (REPO=path)
	python scripts/promote_to_deterministic.py --findings $(SEMANTIC_REVIEW_HISTORY)

plan-registry:  ## Build cross-repo plan registry (SCAN_DIR=~/projects)
	python scripts/build_plan_registry.py --scan-dir $(SCAN_DIR) --output generated/plan_registry.json --summary

ecosystem-deps:  ## Build ecosystem cross-repo dependency map from generated/inferred_*.json
	python scripts/build_ecosystem_dep_map.py --output generated/ecosystem_dep_map.json --summary

infer-all:  ## Infer deps across all governed repos in SCAN_DIR (writes generated/inferred_*.json)
	@find $(SCAN_DIR) -maxdepth 2 -name "meta-process.yaml" | while read config; do \
	  repo=$$(dirname "$$config"); \
	  name=$$(basename "$$repo"); \
	  echo "Inferring $$name ..."; \
	  python scripts/infer_dependencies.py "$$repo" --output generated/inferred_$$name.json; \
	done

agents-md:  ## Regenerate AGENTS.md from CLAUDE.md (Codex-facing projection)
	python scripts/render_agents_md.py --source CLAUDE.md --output AGENTS.md

status:  ## Git status
	@git status --short --branch
