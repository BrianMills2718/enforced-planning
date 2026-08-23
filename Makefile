## enforced-planning — framework for enforced planning, context gating, doc-code alignment

.PHONY: help test test-quick check lint dead-code dead-code-audit dead-code-validate push-check infer check-deps check-caps migrate-rels verify-couplings review-surfaces promote plan-registry ecosystem-status docstring-wiki docstring-wiki-check test-relationships status reachability reachability-check reachability-baseline repo-stats fleet-drift fleet-drift-json

PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
PROJECT_STATUS_PYTHON ?= $(PYTHON)
PROJECT_STATUS_SCRIPT ?= scripts/project_status.py
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

dead-code:  ## Run dead code detection
	$(PYTHON) scripts/check_dead_code.py

dead-code-audit:  ## Refresh reviewed dead-code audit file
	$(PYTHON) scripts/audit_dead_code.py --write

dead-code-validate:  ## Validate reviewed dead-code dispositions
	$(PYTHON) scripts/validate_dead_code_audit.py

reachability:  ## Report module reachability (no gating)
	$(PYTHON) scripts/check_reachability.py --project-root .

reachability-check:  ## Fail if reachability regressed since the baseline (the hook's own check)
	$(PYTHON) scripts/check_reachability.py --project-root . --check

reachability-baseline:  ## Lower the reachability ratchet baseline to the current count
	$(PYTHON) scripts/check_reachability.py --project-root . --write-baseline

repo-stats:  ## Print session-start repetition counters
	$(PYTHON) scripts/repo_stats_block.py --project-root .

FLEET_DRIFT_ARGS ?=

fleet-drift:  ## Report vendored enforced_planning drift across consumer repos
	$(PYTHON) scripts/fleet_drift.py $(FLEET_DRIFT_ARGS)

# Silenced with @: make echoes the recipe line to stdout, which would put a
# non-JSON first line in front of the payload and break `| jq`.
fleet-drift-json:  ## Same report as machine-readable JSON
	@$(PYTHON) scripts/fleet_drift.py --json $(FLEET_DRIFT_ARGS)

push-check:  ## Validate branch push safety against default-branch and coordination state
	$(PYTHON) scripts/check_push_safety.py

## --- Relationships V2 tools ---

infer:  ## Infer dependency graph for a repo (REPO=path)
	python scripts/infer_dependencies.py $(REPO)

check-deps:  ## Validate plan dependency references (REPO=path to plans dir)
	python scripts/check_plan_deps.py $(REPO)/docs/plans/ --scan-dir $(SCAN_DIR)

check-caps:  ## Validate plan Capabilities sections (REPO=path to plans dir)
	python scripts/check_plan_capabilities.py $(REPO)/docs/plans/

migrate-rels:  ## Migrate relationships.yaml V1→V2 (REPO=path)
	python scripts/migrate_relationships.py $(REPO)/relationships.yaml --dry-run

docstring-wiki:  ## Regenerate the source-derived docstring wiki (REPO=path)
	$(PYTHON) scripts/docstring_wiki.py --repo-root $(REPO) --write

docstring-wiki-check:  ## Fail if the source-derived docstring wiki is missing or stale
	$(PYTHON) scripts/docstring_wiki.py --repo-root $(REPO) --check

test-relationships:  ## Report requirement/risk-linked test quality (REPO=path)
	$(PYTHON) scripts/test_relationships.py --repo-root $(REPO)

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

ecosystem-status: ## Build ecosystem status JSON and rendered markdown surface
	$(PYTHON) scripts/ecosystem_status.py

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

status:  ## Verify repository authority freshness and show branch status
	@$(PROJECT_STATUS_PYTHON) $(PROJECT_STATUS_SCRIPT) --repo-root .

# >>> META-PROCESS WORKTREE TARGETS >>>
WORKTREE_CREATE_SCRIPT := scripts/meta/worktree-coordination/create_worktree.py
WORKTREE_REMOVE_SCRIPT := scripts/meta/worktree-coordination/safe_worktree_remove.py
WORKTREE_CLAIMS_SCRIPT := scripts/meta/worktree-coordination/../check_coordination_claims.py
WORKTREE_SESSION_START_SCRIPT := $(if $(wildcard scripts/session_start.py),scripts/session_start.py,scripts/meta/worktree-coordination/../session_start.py)
WORKTREE_SESSION_HEARTBEAT_SCRIPT := $(if $(wildcard scripts/session_heartbeat.py),scripts/session_heartbeat.py,scripts/meta/worktree-coordination/../session_heartbeat.py)
WORKTREE_SESSION_STATUS_SCRIPT := scripts/meta/worktree-coordination/../session_status.py
WORKTREE_SESSION_END_SCRIPT := scripts/meta/worktree-coordination/../session_end.py
WORKTREE_SESSION_FINISH_SCRIPT := scripts/meta/worktree-coordination/../session_finish.py
WORKTREE_SESSION_CLOSE_SCRIPT := scripts/meta/worktree-coordination/../session_close.py
WORKTREE_REVIEW_CLAIM_SCRIPT := scripts/meta/worktree-coordination/create_review_claim.py
WORKTREE_RAISE_CONCERN_SCRIPT := scripts/meta/worktree-coordination/raise_concern.py
WORKTREE_PLAN_READINESS_SCRIPT := scripts/check_plan_readiness.py
SURFACE_RUNTIME_SCRIPT := scripts/surface_runtime.py
WORKTREE_DIR ?= $(shell $(PYTHON) "$(WORKTREE_CREATE_SCRIPT)" --repo-root . --print-default-worktree-dir)
WORKTREE_REPO_ROOT ?= $(shell git rev-parse --path-format=absolute --git-common-dir 2>/dev/null | sed 's|/\.git$$||')
WORKTREE_START_POINT ?= HEAD
WORKTREE_START_REVISION := $(shell git -C "$(WORKTREE_REPO_ROOT)" rev-parse --verify "$(WORKTREE_START_POINT)^{commit}" 2>/dev/null)
WORKTREE_PROJECT ?= $(shell $(PYTHON) "$(WORKTREE_CREATE_SCRIPT)" --repo-root . --print-canonical-project)
WORKTREE_AGENT ?= $(shell if [ -n "$$CODEX_THREAD_ID" ]; then printf codex; elif [ -n "$$CLAUDE_SESSION_ID" ] || [ -n "$$CLAUDE_CODE_SSE_PORT" ]; then printf claude-code; elif [ -n "$$OPENCLAW_SESSION_ID" ] || [ -n "$$OPENCLAW_RUN_ID" ]; then printf openclaw; fi)
SESSION_GOAL ?=
SESSION_PHASE ?=
SESSION_NEXT ?=
SESSION_DEPENDS ?=
SESSION_STOP_CONDITIONS ?=
SESSION_NOTE ?=
SESSION_ALLOW_PARALLEL ?=
ALLOW_UNPLANNED ?=
PLAN_RESUME ?=
WORKTREE_EXECUTION_PROFILE ?= coordinated
PLAN_PROJECT ?= $(WORKTREE_PROJECT)
PLAN_READINESS_COMMAND ?=
SESSION_CLAIM_TYPE ?= program
SESSION_PARENT_SCOPE ?=
SESSION_WRITE_PATHS ?=
SESSION_READ_PATHS ?=
SESSION_WORK_GRAPH ?=
SESSION_WORK_UNIT_ID ?=
OUTCOME_ADMISSION_BOOTSTRAP_PLAN ?=
OUTCOME_ADMISSION_SELECTED ?=
OUTCOME_ADMISSION_RECEIPT_PATH ?=
WORKTREE_DISPOSITION ?= merged
WORKTREE_DISPOSITION_REASON ?=
WORKTREE_RECOVERY_REF ?=
WORKTREE_ALLOW_DISCARD_UNIQUE ?=
WORKTREE_MERGE_COMMIT ?=
REVIEW_SCOPE ?=
REVIEW_NOTES ?=
RECIPIENT ?=

.PHONY: outcome-bootstrap worktree maintenance-worktree worktree-list worktree-remove session-start session-heartbeat session-status session-end session-finish session-close review-claim raise-concern verification-batch-freeze verification-batch-check verification-batch-thaw surface-up surface-preview surface-status surface-down surface-audit

verification-batch-freeze:  ## Freeze clean HEAD for DECISION="..." VERIFY_COMMAND="..."
	@test -n "$(DECISION)" || (echo "DECISION is required" && exit 1)
	@test -n "$(VERIFY_COMMAND)" || (echo "VERIFY_COMMAND is required" && exit 1)
	$(PYTHON) scripts/verification_batch.py --repo-root . freeze --decision "$(DECISION)" --command "$(VERIFY_COMMAND)" $(if $(ALLOW_UNTRACKED),--allow-untracked "$(ALLOW_UNTRACKED)",)

verification-batch-check:  ## Require the active batch to match exact clean HEAD
	$(PYTHON) scripts/verification_batch.py --repo-root . check --require-active

verification-batch-thaw:  ## Invalidate the batch with REASON="..." before a scoped fix
	@test -n "$(REASON)" || (echo "REASON is required" && exit 1)
	$(PYTHON) scripts/verification_batch.py --repo-root . thaw --reason "$(REASON)"

outcome-bootstrap:  ## Create one restricted unplanned outcome lane (PLAN=N plus worktree inputs)
ifndef PLAN
	$(error PLAN is required. Usage: make outcome-bootstrap PLAN=123 BRANCH=plan-123-feature TASK="..." SESSION_GOAL="..." SESSION_PHASE="..." SESSION_WRITE_PATHS="...")
endif
	@$(MAKE) worktree PLAN= WORKTREE_EXECUTION_PROFILE=light ALLOW_UNPLANNED=1 \
		OUTCOME_ADMISSION_BOOTSTRAP_PLAN="$(PLAN)"

worktree:  ## Create claimed worktree (BRANCH=name TASK="..." [PLAN=N] [AGENT=name])
ifndef BRANCH
	$(error BRANCH is required. Usage: make worktree BRANCH=plan-42-feature TASK="Describe the task")
endif
ifndef TASK
	$(error TASK is required. Usage: make worktree BRANCH=plan-42-feature TASK="Describe the task")
endif
ifndef SESSION_GOAL
	$(error SESSION_GOAL is required. Name the broader objective, not the local branch)
endif
ifndef SESSION_PHASE
	$(error SESSION_PHASE is required. Describe the current execution phase)
endif
ifndef WORKTREE_AGENT
	$(error Unable to infer agent runtime. Set AGENT via WORKTREE_AGENT=codex|claude-code|openclaw)
endif
	@if [ -n "$(OUTCOME_ADMISSION_BOOTSTRAP_PLAN)" ]; then \
		$(PYTHON) scripts/outcome_admission.py bootstrap \
			--plan "$(OUTCOME_ADMISSION_BOOTSTRAP_PLAN)" \
			$(foreach path,$(SESSION_WRITE_PATHS),--write-path "$(path)") \
			$(if $(OUTCOME_ADMISSION_RECEIPT_PATH),--receipt-path "$(OUTCOME_ADMISSION_RECEIPT_PATH)",); \
	fi
	@if [ ! -f "$(WORKTREE_CREATE_SCRIPT)" ]; then \
		echo "Missing worktree coordination module: $(WORKTREE_CREATE_SCRIPT)"; \
		echo "Install or sync the sanctioned worktree-coordination module before using make worktree."; \
		exit 1; \
	fi
	@if [ ! -f "$(WORKTREE_CLAIMS_SCRIPT)" ]; then \
		echo "Missing worktree coordination module: $(WORKTREE_CLAIMS_SCRIPT)"; \
		echo "Install or sync the sanctioned worktree-coordination module before using make worktree."; \
		exit 1; \
	fi
	@if [ ! -f "$(WORKTREE_SESSION_START_SCRIPT)" ]; then \
		echo "Missing session lifecycle module: $(WORKTREE_SESSION_START_SCRIPT)"; \
		echo "Install or sync the sanctioned session lifecycle module before using make worktree."; \
		exit 1; \
	fi
	@test -n "$(WORKTREE_START_REVISION)" || { \
		echo "Unable to resolve one full Git start revision from $(WORKTREE_START_POINT)"; \
		exit 1; \
	}
	@$(PYTHON) "$(WORKTREE_PLAN_READINESS_SCRIPT)" \
		$(if $(PLAN),--qualified-plan-id "$(PLAN_PROJECT)#$(PLAN)",) \
		--execution-profile "$(WORKTREE_EXECUTION_PROFILE)" \
		--repo-root "$(WORKTREE_REPO_ROOT)" \
		--start-point "$(WORKTREE_START_REVISION)" \
		$(if $(PLAN_READINESS_COMMAND),--query-command "$(PLAN_READINESS_COMMAND)",) \
		--repository "$(WORKTREE_PROJECT)" \
		--lane-id "$(BRANCH)" \
		$(if $(SESSION_PARENT_SCOPE),--parent-lane-id "$(SESSION_PARENT_SCOPE)",) \
		--branch "$(BRANCH)" \
		--worktree-path "$(WORKTREE_DIR)/$(BRANCH)" \
		--agent "$(WORKTREE_AGENT)" \
		--scope "$(BRANCH)" \
		$(if $(PLAN_RESUME),--resume,) \
		$(if $(ALLOW_UNPLANNED),--allow-unplanned,)
	@$(PYTHON) "$(WORKTREE_CLAIMS_SCRIPT)" --claim \
		--agent "$(WORKTREE_AGENT)" \
		--project "$(WORKTREE_PROJECT)" \
		--scope "$(BRANCH)" \
		--intent "$(TASK)" \
		--claim-type "$(SESSION_CLAIM_TYPE)" \
		--repo-root "$(WORKTREE_REPO_ROOT)" \
		--branch "$(BRANCH)" \
		--worktree-path "$(WORKTREE_DIR)/$(BRANCH)" \
		--start-point "$(WORKTREE_START_REVISION)" \
		--require-new \
		$(if $(PLAN_RESUME),--resume,) \
		--session-name "$(SESSION_GOAL)" \
		--broader-goal "$(SESSION_GOAL)" \
		$(if $(SESSION_PARENT_SCOPE),--parent-scope "$(SESSION_PARENT_SCOPE)",) \
		$(if $(filter 1 true yes,$(SESSION_ALLOW_PARALLEL)),--allow-parallel,) \
		$(foreach path,$(SESSION_WRITE_PATHS),--write-path "$(path)") \
		$(foreach path,$(SESSION_READ_PATHS),--read-path "$(path)") \
		$(if $(SESSION_WORK_GRAPH),--work-graph "$(SESSION_WORK_GRAPH)",) \
		$(if $(SESSION_WORK_UNIT_ID),--work-unit-id "$(SESSION_WORK_UNIT_ID)",) \
		$(if $(PLAN),--plan "$(PLAN_PROJECT)#$(PLAN)",)
	@mkdir -p "$(WORKTREE_DIR)"
	@creation_receipt=$$(mktemp "$(WORKTREE_DIR)/.worktree-create.XXXXXX.json"); \
	trap 'rm -f "$$creation_receipt"' EXIT HUP INT TERM; \
	if ! $(PYTHON) "$(WORKTREE_CREATE_SCRIPT)" \
		--repo-root "$(WORKTREE_REPO_ROOT)" \
		--path "$(WORKTREE_DIR)/$(BRANCH)" \
		--branch "$(BRANCH)" \
		--start-point "$(WORKTREE_START_REVISION)" \
		--require-write-claim \
		--claim-agent "$(WORKTREE_AGENT)" \
		--claim-project "$(WORKTREE_PROJECT)" \
		$(foreach path,$(SESSION_WRITE_PATHS),--claim-write-path "$(path)") \
		$(if $(PLAN),--claim-start-revision "$(WORKTREE_START_REVISION)",) \
		--json > "$$creation_receipt"; then \
		if ! $(PYTHON) -c 'import json, sys; payload=json.load(open(sys.argv[1], encoding="utf-8")); print("Worktree creation failed: " + payload["message"], file=sys.stderr)' "$$creation_receipt"; then \
			echo "Worktree creation failed and its receipt was unreadable." >&2; \
		fi; \
		if ! created_branch=$$($(PYTHON) -c 'import json, sys; print(1 if json.load(open(sys.argv[1], encoding="utf-8"))["created_branch"] else 0)' "$$creation_receipt"); then \
			echo "Worktree creation failed without a readable ownership receipt; claim retained."; \
			exit 1; \
		fi; \
		unsafe_residue=0; \
		if [ -e "$(WORKTREE_DIR)/$(BRANCH)" ]; then unsafe_residue=1; fi; \
		if [ "$$created_branch" -eq 1 ] && git -C "$(WORKTREE_REPO_ROOT)" show-ref --verify --quiet "refs/heads/$(BRANCH)"; then unsafe_residue=1; fi; \
		if [ "$$unsafe_residue" -eq 0 ]; then \
			$(PYTHON) "$(WORKTREE_CLAIMS_SCRIPT)" --release \
				--agent "$(WORKTREE_AGENT)" --project "$(WORKTREE_PROJECT)" --scope "$(BRANCH)" \
				--require-current-session \
				$(if $(PLAN),--expected-start-revision "$(WORKTREE_START_REVISION)",) || exit 1; \
		else \
			echo "Worktree creation failed with recoverable branch/worktree residue; claim retained."; \
		fi; \
		exit 1; \
	fi; \
	if ! created_branch=$$($(PYTHON) -c 'import json, sys; print(1 if json.load(open(sys.argv[1], encoding="utf-8"))["created_branch"] else 0)' "$$creation_receipt"); then \
		echo "Worktree was created without a readable ownership receipt; claim retained."; \
		exit 1; \
	fi; \
	if ! $(PYTHON) "$(WORKTREE_SESSION_START_SCRIPT)" \
		--agent "$(WORKTREE_AGENT)" \
		--project "$(WORKTREE_PROJECT)" \
		--scope "$(BRANCH)" \
		--intent "$(TASK)" \
		--repo-root "$(WORKTREE_REPO_ROOT)" \
		--worktree-path "$(WORKTREE_DIR)/$(BRANCH)" \
		--branch "$(BRANCH)" \
		--broader-goal "$(SESSION_GOAL)" \
		--current-phase "$(SESSION_PHASE)" \
		--claim-type "$(SESSION_CLAIM_TYPE)" \
		$(if $(SESSION_PARENT_SCOPE),--parent-scope "$(SESSION_PARENT_SCOPE)",) \
		$(if $(filter 1 true yes,$(SESSION_ALLOW_PARALLEL)),--allow-parallel,) \
		$(foreach path,$(SESSION_WRITE_PATHS),--write-path "$(path)") \
		$(foreach path,$(SESSION_READ_PATHS),--read-path "$(path)") \
		$(if $(SESSION_WORK_GRAPH),--work-graph "$(SESSION_WORK_GRAPH)",) \
		$(if $(SESSION_WORK_UNIT_ID),--work-unit-id "$(SESSION_WORK_UNIT_ID)",) \
		$(if $(PLAN),--plan "$(PLAN_PROJECT)#$(PLAN)",) \
		$(if $(PLAN),--start-revision "$(WORKTREE_START_REVISION)",) \
		$(if $(ALLOW_UNPLANNED),--allow-unplanned,) \
		$(if $(SESSION_NEXT),--next-phase "$(SESSION_NEXT)",) \
		$(if $(SESSION_DEPENDS),--depends-on "$(SESSION_DEPENDS)",) \
		$(if $(SESSION_STOP_CONDITIONS),--stop-condition "$(SESSION_STOP_CONDITIONS)",) \
		$(if $(SESSION_NOTE),--notes "$(SESSION_NOTE)",) \
		$(if $(filter 1 true yes,$(OUTCOME_ADMISSION_SELECTED)),--outcome-selected,) \
		$(if $(OUTCOME_ADMISSION_BOOTSTRAP_PLAN),--outcome-bootstrap-plan "$(OUTCOME_ADMISSION_BOOTSTRAP_PLAN)",) \
		$(if $(OUTCOME_ADMISSION_RECEIPT_PATH),--outcome-admission-receipt-path "$(OUTCOME_ADMISSION_RECEIPT_PATH)",); then \
		cleanup_ok=1; \
		git -C "$(WORKTREE_REPO_ROOT)" worktree remove --force "$(WORKTREE_DIR)/$(BRANCH)" || cleanup_ok=0; \
		if [ "$$created_branch" -eq 1 ]; then \
			git -C "$(WORKTREE_REPO_ROOT)" branch -D "$(BRANCH)" || cleanup_ok=0; \
		fi; \
		if [ "$$cleanup_ok" -eq 1 ]; then \
			$(PYTHON) "$(WORKTREE_CLAIMS_SCRIPT)" --release \
				--agent "$(WORKTREE_AGENT)" --project "$(WORKTREE_PROJECT)" --scope "$(BRANCH)" \
				--require-current-session \
				$(if $(PLAN),--expected-start-revision "$(WORKTREE_START_REVISION)",) || exit 1; \
		else \
			echo "Session start failed and exact cleanup was incomplete; claim retained."; \
		fi; \
		exit 1; \
	fi; \
	rm -f "$$creation_receipt"; \
	trap - EXIT HUP INT TERM
	@echo ""
	@echo "Worktree created at $(WORKTREE_DIR)/$(BRANCH)"
	@echo "Claim created for branch $(BRANCH)"
	@echo "Session contract started for $(SESSION_GOAL)"

maintenance-worktree:  ## Create a claimed light maintenance worktree without a numbered plan
	@$(MAKE) worktree BRANCH="$(BRANCH)" TASK="$(TASK)" SESSION_GOAL="$(SESSION_GOAL)" \
		SESSION_PHASE="$(SESSION_PHASE)" AGENT="$(WORKTREE_AGENT)" \
		SESSION_WRITE_PATHS="$(SESSION_WRITE_PATHS)" SESSION_READ_PATHS="$(SESSION_READ_PATHS)" \
		SESSION_NEXT="$(SESSION_NEXT)" SESSION_DEPENDS="$(SESSION_DEPENDS)" \
		WORKTREE_EXECUTION_PROFILE=light ALLOW_UNPLANNED=1

session-start:  ## Create or refresh the active session contract for BRANCH=name
ifndef BRANCH
	$(error BRANCH is required. Usage: make session-start BRANCH=plan-42-feature TASK="..." SESSION_GOAL="..." SESSION_PHASE="...")
endif
ifndef TASK
	$(error TASK is required. Usage: make session-start BRANCH=plan-42-feature TASK="...")
endif
ifndef SESSION_GOAL
	$(error SESSION_GOAL is required. Name the broader objective, not the local branch)
endif
ifndef SESSION_PHASE
	$(error SESSION_PHASE is required. Describe the current execution phase)
endif
ifndef WORKTREE_AGENT
	$(error Unable to infer agent runtime. Set AGENT via WORKTREE_AGENT=codex|claude-code|openclaw)
endif
	@$(PYTHON) "$(WORKTREE_SESSION_START_SCRIPT)" \
		--agent "$(WORKTREE_AGENT)" \
		--project "$(WORKTREE_PROJECT)" \
		--scope "$(BRANCH)" \
		--intent "$(TASK)" \
		--repo-root "$(WORKTREE_REPO_ROOT)" \
		--worktree-path "$(WORKTREE_DIR)/$(BRANCH)" \
		--branch "$(BRANCH)" \
		--broader-goal "$(SESSION_GOAL)" \
		--current-phase "$(SESSION_PHASE)" \
		--claim-type "$(SESSION_CLAIM_TYPE)" \
		$(if $(SESSION_PARENT_SCOPE),--parent-scope "$(SESSION_PARENT_SCOPE)",) \
		$(if $(filter 1 true yes,$(SESSION_ALLOW_PARALLEL)),--allow-parallel,) \
		$(foreach path,$(SESSION_WRITE_PATHS),--write-path "$(path)") \
		$(foreach path,$(SESSION_READ_PATHS),--read-path "$(path)") \
		$(if $(SESSION_WORK_GRAPH),--work-graph "$(SESSION_WORK_GRAPH)",) \
		$(if $(SESSION_WORK_UNIT_ID),--work-unit-id "$(SESSION_WORK_UNIT_ID)",) \
		$(if $(PLAN),--plan "$(PLAN_PROJECT)#$(PLAN)",) \
		$(if $(SESSION_NEXT),--next-phase "$(SESSION_NEXT)",) \
		$(if $(SESSION_DEPENDS),--depends-on "$(SESSION_DEPENDS)",) \
		$(if $(SESSION_STOP_CONDITIONS),--stop-condition "$(SESSION_STOP_CONDITIONS)",) \
		$(if $(SESSION_NOTE),--notes "$(SESSION_NOTE)",) \
		$(if $(filter 1 true yes,$(OUTCOME_ADMISSION_SELECTED)),--outcome-selected,) \
		$(if $(OUTCOME_ADMISSION_BOOTSTRAP_PLAN),--outcome-bootstrap-plan "$(OUTCOME_ADMISSION_BOOTSTRAP_PLAN)",) \
		$(if $(OUTCOME_ADMISSION_RECEIPT_PATH),--outcome-admission-receipt-path "$(OUTCOME_ADMISSION_RECEIPT_PATH)",)

session-heartbeat:  ## Refresh heartbeat and optional phase for BRANCH=name
ifndef BRANCH
	$(error BRANCH is required. Usage: make session-heartbeat BRANCH=plan-42-feature)
endif
ifndef WORKTREE_AGENT
	$(error Unable to infer agent runtime. Set AGENT via WORKTREE_AGENT=codex|claude-code|openclaw)
endif
	@$(PYTHON) "$(WORKTREE_SESSION_HEARTBEAT_SCRIPT)" \
		--agent "$(WORKTREE_AGENT)" \
		--project "$(WORKTREE_PROJECT)" \
		--scope "$(BRANCH)" \
		--branch "$(BRANCH)" \
		$(if $(SESSION_PHASE),--current-phase "$(SESSION_PHASE)",) \
		$(if $(filter 1 true yes,$(OUTCOME_ADMISSION_SELECTED)),--outcome-selected,) \
		$(if $(OUTCOME_ADMISSION_RECEIPT_PATH),--outcome-admission-receipt-path "$(OUTCOME_ADMISSION_RECEIPT_PATH)",)

session-status:  ## Show live session summaries for this repo
	@$(PYTHON) "$(WORKTREE_SESSION_STATUS_SCRIPT)" --project "$(WORKTREE_PROJECT)"

session-end:  ## Retire this runtime session's live claims without deleting Git work
ifndef WORKTREE_AGENT
	$(error Unable to infer agent runtime. Set AGENT via WORKTREE_AGENT=codex|claude-code|openclaw)
endif
	@$(PYTHON) "$(WORKTREE_SESSION_END_SCRIPT)" \
		--agent "$(WORKTREE_AGENT)" \
		$(if $(SESSION_NOTE),--reason "$(SESSION_NOTE)",)

session-finish:  ## Finish the session for BRANCH=name; blocks if the worktree is dirty
ifndef BRANCH
	$(error BRANCH is required. Usage: make session-finish BRANCH=plan-42-feature)
endif
ifndef WORKTREE_AGENT
	$(error Unable to infer agent runtime. Set AGENT via WORKTREE_AGENT=codex|claude-code|openclaw)
endif
	@$(PYTHON) "$(WORKTREE_SESSION_FINISH_SCRIPT)" \
		--agent "$(WORKTREE_AGENT)" \
		--project "$(WORKTREE_PROJECT)" \
		--scope "$(BRANCH)" \
		--worktree-path "$(WORKTREE_DIR)/$(BRANCH)" \
		$(if $(SESSION_NOTE),--note "$(SESSION_NOTE)",)

session-close:  ## Close the claimed lane for BRANCH=name: cleanup worktree + branch + claim together
ifndef BRANCH
	$(error BRANCH is required. Usage: make session-close BRANCH=plan-42-feature)
endif
ifndef WORKTREE_AGENT
	$(error Unable to infer agent runtime. Set AGENT via WORKTREE_AGENT=codex|claude-code|openclaw)
endif
	@$(PYTHON) "$(WORKTREE_SESSION_CLOSE_SCRIPT)" \
		--agent "$(WORKTREE_AGENT)" \
		--project "$(WORKTREE_PROJECT)" \
		--scope "$(BRANCH)" \
		--worktree-path "$(WORKTREE_DIR)/$(BRANCH)" \
		--branch "$(BRANCH)" \
		--disposition "$(WORKTREE_DISPOSITION)" \
		--disposition-reason "$(WORKTREE_DISPOSITION_REASON)" \
		--recovery-ref "$(WORKTREE_RECOVERY_REF)" \
		$(if $(filter 1 true yes,$(WORKTREE_ALLOW_DISCARD_UNIQUE)),--allow-discard-unique,) \
		$(if $(WORKTREE_MERGE_COMMIT),--merge-commit "$(WORKTREE_MERGE_COMMIT)",) \
		$(if $(SESSION_NOTE),--note "$(SESSION_NOTE)",)

worktree-list:  ## Show claimed worktree coordination status
	@if [ ! -f "$(WORKTREE_CLAIMS_SCRIPT)" ]; then \
		echo "Missing worktree coordination module: $(WORKTREE_CLAIMS_SCRIPT)"; \
		echo "Install or sync the sanctioned worktree-coordination module before using make worktree-list."; \
		exit 1; \
	fi
	@$(PYTHON) "$(WORKTREE_CLAIMS_SCRIPT)" --list

worktree-remove:  ## Safely remove worktree for BRANCH=name
ifndef BRANCH
	$(error BRANCH is required. Usage: make worktree-remove BRANCH=plan-42-feature)
endif
	@if [ ! -f "$(WORKTREE_SESSION_CLOSE_SCRIPT)" ]; then \
		echo "Missing session lifecycle module: $(WORKTREE_SESSION_CLOSE_SCRIPT)"; \
		echo "Install or sync the sanctioned session lifecycle module before using make worktree-remove."; \
		exit 1; \
	fi
	@$(MAKE) session-close BRANCH="$(BRANCH)" \
		$(if $(WORKTREE_MERGE_COMMIT),WORKTREE_MERGE_COMMIT="$(WORKTREE_MERGE_COMMIT)",) \
		$(if $(SESSION_NOTE),SESSION_NOTE="$(SESSION_NOTE)",)

review-claim:  ## Create a review claim for TARGET_BRANCH=name WRITE_PATHS="a|b" TASK="..."
ifndef TARGET_BRANCH
	$(error TARGET_BRANCH is required. Usage: make review-claim TARGET_BRANCH=plan-42-feature WRITE_PATHS="src/foo.py|tests/test_foo.py" TASK="Review concern")
endif
ifndef WRITE_PATHS
	$(error WRITE_PATHS is required. Provide one or more repo-relative paths separated by '|')
endif
ifndef TASK
	$(error TASK is required. Describe the review intent)
endif
ifndef SESSION_GOAL
	$(error SESSION_GOAL is required. Name the broader review objective)
endif
ifndef WORKTREE_AGENT
	$(error Unable to infer agent runtime. Set AGENT via WORKTREE_AGENT=codex|claude-code|openclaw)
endif
	@$(PYTHON) "$(WORKTREE_REVIEW_CLAIM_SCRIPT)" \
		--repo-root "$(CURDIR)" \
		--agent "$(WORKTREE_AGENT)" \
		--project "$(WORKTREE_PROJECT)" \
		--target-branch "$(TARGET_BRANCH)" \
		--intent "$(TASK)" \
		--session-name "$(SESSION_GOAL)" \
		--write-path "$(WRITE_PATHS)" \
		$(if $(PLAN),--plan "Plan #$(PLAN)",) \
		$(if $(REVIEW_SCOPE),--scope "$(REVIEW_SCOPE)",) \
		$(if $(REVIEW_NOTES),--notes "$(REVIEW_NOTES)",)

raise-concern:  ## Route concern to TARGET_BRANCH via PR comment or local inbox
ifndef TARGET_BRANCH
	$(error TARGET_BRANCH is required. Usage: make raise-concern TARGET_BRANCH=plan-42-feature SUBJECT="..." MESSAGE="...")
endif
ifndef SUBJECT
	$(error SUBJECT is required. Usage: make raise-concern TARGET_BRANCH=plan-42-feature SUBJECT="..." MESSAGE="...")
endif
ifndef WORKTREE_AGENT
	$(error Unable to infer agent runtime. Set AGENT via WORKTREE_AGENT=codex|claude-code|openclaw)
endif
ifndef MESSAGE
ifndef MESSAGE_FILE
	$(error MESSAGE or MESSAGE_FILE is required. Provide inline content or a path to a concern file)
endif
endif
	@$(PYTHON) "$(WORKTREE_RAISE_CONCERN_SCRIPT)" \
		--repo-root "$(CURDIR)" \
		--agent "$(WORKTREE_AGENT)" \
		--project "$(WORKTREE_PROJECT)" \
		--target-branch "$(TARGET_BRANCH)" \
		--subject "$(SUBJECT)" \
		$(if $(MESSAGE),--content "$(MESSAGE)",) \
		$(if $(MESSAGE_FILE),--content-file "$(MESSAGE_FILE)",) \
		$(if $(RECIPIENT),--recipient "$(RECIPIENT)",)

surface-up:  ## Start the registered canonical UI (SURFACE=id)
	@test -n "$(SURFACE)" || { echo "SURFACE is required" >&2; exit 2; }
	$(PYTHON) "$(SURFACE_RUNTIME_SCRIPT)" --repo-root . up "$(SURFACE)"

surface-preview:  ## Start a registered preview on noncanonical ports (SURFACE=id)
	@test -n "$(SURFACE)" || { echo "SURFACE is required" >&2; exit 2; }
	$(PYTHON) "$(SURFACE_RUNTIME_SCRIPT)" --repo-root . up "$(SURFACE)" --mode preview

surface-status:  ## Show exact surface leases
	$(PYTHON) "$(SURFACE_RUNTIME_SCRIPT)" --repo-root . status

surface-down:  ## Stop the exact selected surface lease (SURFACE=id [LEASE=id])
	@test -n "$(SURFACE)" || { echo "SURFACE is required" >&2; exit 2; }
	$(PYTHON) "$(SURFACE_RUNTIME_SCRIPT)" --repo-root . down "$(SURFACE)" $(if $(LEASE),--lease-id "$(LEASE)",)

surface-audit:  ## Compare registry, lease, process, and served identity (SURFACE=id)
	@test -n "$(SURFACE)" || { echo "SURFACE is required" >&2; exit 2; }
	$(PYTHON) "$(SURFACE_RUNTIME_SCRIPT)" --repo-root . audit "$(SURFACE)" $(if $(REQUIRE_RUNNING),--require-running,)
# <<< META-PROCESS WORKTREE TARGETS <<<
