#!/bin/bash
# Enforced Planning Installation Script
# Usage: ./install.sh /path/to/target/project [--minimal|--full]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${1:-.}"
MODE="${2:---minimal}"

if [[ "$TARGET_DIR" == "-h" || "$TARGET_DIR" == "--help" ]]; then
    echo "Usage: $0 /path/to/project [--minimal|--full]"
    echo ""
    echo "Modes:"
    echo "  --minimal  Install core patterns (plans, git hooks, doc-coupling)"
    echo "  --full     Install all patterns including worktree coordination and acceptance gates"
    echo ""
    echo "After installation, edit meta-process.yaml to configure."
    exit 0
fi

# Resolve target directory
TARGET_DIR="$(cd "$TARGET_DIR" && pwd)"

echo -e "${GREEN}Installing enforced-planning framework to: $TARGET_DIR${NC}"
echo -e "Mode: $MODE"
echo ""

# Check if git repo
if [[ ! -d "$TARGET_DIR/.git" ]]; then
    echo -e "${RED}Error: $TARGET_DIR is not a git repository${NC}"
    exit 1
fi

# Create directories
echo "Creating directories..."
mkdir -p "$TARGET_DIR/docs/plans"
mkdir -p "$TARGET_DIR/scripts/meta"
mkdir -p "$TARGET_DIR/hooks"
mkdir -p "$TARGET_DIR/.claude/hooks"
mkdir -p "$TARGET_DIR/prompts"

if [[ "$MODE" == "--full" ]]; then
    mkdir -p "$TARGET_DIR/acceptance_gates"
    mkdir -p "$TARGET_DIR/docs/adr"
fi

# Copy configuration template
echo "Copying configuration..."
if [[ ! -f "$TARGET_DIR/meta-process.yaml" ]]; then
    cp "$SCRIPT_DIR/templates/meta-process.yaml.example" "$TARGET_DIR/meta-process.yaml"
    echo -e "  ${GREEN}Created: meta-process.yaml${NC}"
else
    echo -e "  ${YELLOW}Skipped: meta-process.yaml (already exists)${NC}"
fi

# Copy scripts
echo "Copying scripts..."
CORE_SCRIPTS=(
    "check_plan_tests.py"
    "check_plan_blockers.py"
    "check_dead_code.py"
    "complete_plan.py"
    "parse_plan.py"
    "sync_plan_status.py"
    "merge_pr.py"
    "pr_auto.py"
    "generate_quiz.py"
)

TRUTH_SURFACE_SCRIPTS=(
    "check_truth_surface_drift.py"
    "render_truth_surface_status.py"
    "review_truth_surface_semantic.py"
    "truth_surface_semantic_models.py"
)

for script in "${CORE_SCRIPTS[@]}"; do
    if [[ -f "$SCRIPT_DIR/scripts/$script" ]]; then
        cp "$SCRIPT_DIR/scripts/$script" "$TARGET_DIR/scripts/meta/"
        echo -e "  ${GREEN}Copied: scripts/meta/$script${NC}"
    fi
done

for script in "${TRUTH_SURFACE_SCRIPTS[@]}"; do
    if [[ -f "$SCRIPT_DIR/scripts/$script" ]]; then
        cp "$SCRIPT_DIR/scripts/$script" "$TARGET_DIR/scripts/"
        echo -e "  ${GREEN}Copied: scripts/$script${NC}"
    fi
done

if [[ "$MODE" == "--full" ]]; then
    FULL_SCRIPTS=(
        "check_doc_coupling.py"
        "sync_governance.py"
        "check_mock_usage.py"
        "check_locked_files.py"
    )
    for script in "${FULL_SCRIPTS[@]}"; do
        if [[ -f "$SCRIPT_DIR/scripts/$script" ]]; then
            cp "$SCRIPT_DIR/scripts/$script" "$TARGET_DIR/scripts/meta/"
            echo -e "  ${GREEN}Copied: scripts/meta/$script${NC}"
        fi
    done

    # Worktree coordination scripts (opt-in module)
    WORKTREE_SCRIPTS=(
        "check_claims.py"
        "safe_worktree_remove.py"
        "finish_pr.py"
        "meta_status.py"
        "check_messages.py"
        "send_message.py"
    )
    mkdir -p "$TARGET_DIR/scripts/meta/worktree-coordination"
    for script in "${WORKTREE_SCRIPTS[@]}"; do
        if [[ -f "$SCRIPT_DIR/scripts/worktree-coordination/$script" ]]; then
            cp "$SCRIPT_DIR/scripts/worktree-coordination/$script" "$TARGET_DIR/scripts/meta/worktree-coordination/"
            echo -e "  ${GREEN}Copied: scripts/meta/worktree-coordination/$script${NC}"
        fi
    done
fi

# Copy git hooks
echo "Copying git hooks..."
for hook in commit-msg pre-commit post-commit; do
    if [[ -f "$SCRIPT_DIR/hooks/git/$hook" ]]; then
        cp "$SCRIPT_DIR/hooks/git/$hook" "$TARGET_DIR/hooks/"
        chmod +x "$TARGET_DIR/hooks/$hook"
        echo -e "  ${GREEN}Copied: hooks/$hook${NC}"
    fi
done

# Copy Claude Code hooks
echo "Copying Claude Code hooks..."
CORE_CLAUDE_HOOKS=(
    "protect-main.sh"
    "check-hook-enabled.sh"
    "check-references-reviewed.sh"
    "track-reads.sh"
    "gate-edit.sh"
    "post-edit-quiz.sh"
)

for hook in "${CORE_CLAUDE_HOOKS[@]}"; do
    if [[ -f "$SCRIPT_DIR/hooks/claude/$hook" ]]; then
        cp "$SCRIPT_DIR/hooks/claude/$hook" "$TARGET_DIR/.claude/hooks/"
        chmod +x "$TARGET_DIR/.claude/hooks/$hook"
        echo -e "  ${GREEN}Copied: .claude/hooks/$hook${NC}"
    fi
done

if [[ "$MODE" == "--full" ]]; then
    # Worktree coordination hooks (opt-in module)
    WORKTREE_CLAUDE_HOOKS=(
        "protect-main.sh"
        "block-cd-worktree.sh"
        "block-worktree-remove.sh"
        "check-cwd-valid.sh"
        "warn-worktree-cwd.sh"
        "check-file-scope.sh"
        "enforce-make-merge.sh"
        "check-inbox.sh"
        "notify-inbox-startup.sh"
    )
    mkdir -p "$TARGET_DIR/.claude/hooks/worktree-coordination"
    for hook in "${WORKTREE_CLAUDE_HOOKS[@]}"; do
        if [[ -f "$SCRIPT_DIR/hooks/claude/worktree-coordination/$hook" ]]; then
            cp "$SCRIPT_DIR/hooks/claude/worktree-coordination/$hook" "$TARGET_DIR/.claude/hooks/worktree-coordination/"
            chmod +x "$TARGET_DIR/.claude/hooks/worktree-coordination/$hook"
            echo -e "  ${GREEN}Copied: .claude/hooks/worktree-coordination/$hook${NC}"
        fi
    done
fi

# Generate .claude/settings.json (wires hooks to Claude Code events)
echo "Configuring Claude Code settings..."
if [[ ! -f "$TARGET_DIR/.claude/settings.json" ]]; then
    if [[ "$MODE" == "--full" ]]; then
        cp "$SCRIPT_DIR/templates/settings.json.full" "$TARGET_DIR/.claude/settings.json"
    else
        cp "$SCRIPT_DIR/templates/settings.json.minimal" "$TARGET_DIR/.claude/settings.json"
    fi
    echo -e "  ${GREEN}Created: .claude/settings.json${NC}"
else
    echo -e "  ${YELLOW}Skipped: .claude/settings.json (already exists)${NC}"
fi

# Copy templates
echo "Copying templates..."
if [[ ! -f "$TARGET_DIR/docs/plans/TEMPLATE.md" ]]; then
    cp "$SCRIPT_DIR/templates/plan.md.template" "$TARGET_DIR/docs/plans/TEMPLATE.md"
    echo -e "  ${GREEN}Created: docs/plans/TEMPLATE.md${NC}"
fi

if [[ ! -f "$TARGET_DIR/docs/plans/CLAUDE.md" ]]; then
    cp "$SCRIPT_DIR/templates/plans-index.md.template" "$TARGET_DIR/docs/plans/CLAUDE.md"
    echo -e "  ${GREEN}Created: docs/plans/CLAUDE.md${NC}"
fi

# Issues tracking (for recording observed problems, concerns, tech debt)
if [[ ! -f "$TARGET_DIR/ISSUES.md" ]]; then
    cp "$SCRIPT_DIR/templates/issues.md.template" "$TARGET_DIR/ISSUES.md"
    echo -e "  ${GREEN}Created: ISSUES.md${NC}"
fi

if [[ ! -f "$TARGET_DIR/truth_surface_drift.yaml.example" ]]; then
    if [[ -f "$SCRIPT_DIR/templates/truth_surface_drift.yaml.example" ]]; then
        cp "$SCRIPT_DIR/templates/truth_surface_drift.yaml.example" "$TARGET_DIR/truth_surface_drift.yaml.example"
        echo -e "  ${GREEN}Created: truth_surface_drift.yaml.example${NC}"
    fi
fi

if [[ ! -f "$TARGET_DIR/prompts/truth_surface_semantic_review.yaml" ]]; then
    if [[ -f "$SCRIPT_DIR/prompts/truth_surface_semantic_review.yaml" ]]; then
        cp "$SCRIPT_DIR/prompts/truth_surface_semantic_review.yaml" "$TARGET_DIR/prompts/truth_surface_semantic_review.yaml"
        echo -e "  ${GREEN}Created: prompts/truth_surface_semantic_review.yaml${NC}"
    fi
fi

if [[ "$MODE" == "--full" ]]; then
    if [[ ! -f "$TARGET_DIR/scripts/relationships.yaml" ]]; then
        if [[ -f "$SCRIPT_DIR/templates/relationships.yaml.example" ]]; then
            cp "$SCRIPT_DIR/templates/relationships.yaml.example" "$TARGET_DIR/scripts/relationships.yaml"
            echo -e "  ${GREEN}Created: scripts/relationships.yaml${NC}"
        elif [[ -f "$SCRIPT_DIR/templates/doc_coupling.yaml.example" ]]; then
            cp "$SCRIPT_DIR/templates/doc_coupling.yaml.example" "$TARGET_DIR/scripts/relationships.yaml"
            echo -e "  ${GREEN}Created: scripts/relationships.yaml${NC}"
        fi
    fi

    if [[ ! -f "$TARGET_DIR/acceptance_gates/EXAMPLE.yaml" ]]; then
        cp "$SCRIPT_DIR/templates/acceptance_gate.yaml.example" "$TARGET_DIR/acceptance_gates/EXAMPLE.yaml"
        echo -e "  ${GREEN}Created: acceptance_gates/EXAMPLE.yaml${NC}"
    fi
fi

# Copy Makefile additions
echo "Copying Makefile targets..."
if [[ -f "$SCRIPT_DIR/templates/Makefile.meta" ]]; then
    if [[ -f "$TARGET_DIR/Makefile" ]]; then
        if ! grep -q "# === META-PROCESS ===" "$TARGET_DIR/Makefile" && ! grep -q "# === ENFORCED PLANNING TARGETS ===" "$TARGET_DIR/Makefile"; then
            echo "" >> "$TARGET_DIR/Makefile"
            cat "$SCRIPT_DIR/templates/Makefile.meta" >> "$TARGET_DIR/Makefile"
            echo -e "  ${GREEN}Appended enforced-planning targets to Makefile${NC}"
        else
            echo -e "  ${YELLOW}Skipped: Makefile (already has enforced-planning targets)${NC}"
        fi
    else
        cp "$SCRIPT_DIR/templates/Makefile.meta" "$TARGET_DIR/Makefile"
        echo -e "  ${GREEN}Created: Makefile${NC}"
    fi
fi

# Set up git hooks symlink
echo "Setting up git hooks..."
if [[ -d "$TARGET_DIR/.git" ]]; then
    git -C "$TARGET_DIR" config core.hooksPath hooks
    echo -e "  ${GREEN}Configured git to use hooks/ directory${NC}"
fi

# Copy pattern documentation
echo "Copying pattern documentation..."
mkdir -p "$TARGET_DIR/docs/meta-patterns"
cp "$SCRIPT_DIR/patterns/"*.md "$TARGET_DIR/docs/meta-patterns/" 2>/dev/null || true
echo -e "  ${GREEN}Copied core pattern documentation to docs/meta-patterns/${NC}"

if [[ "$MODE" == "--full" ]]; then
    mkdir -p "$TARGET_DIR/docs/meta-patterns/worktree-coordination"
    cp "$SCRIPT_DIR/patterns/worktree-coordination/"*.md "$TARGET_DIR/docs/meta-patterns/worktree-coordination/" 2>/dev/null || true
    echo -e "  ${GREEN}Copied worktree coordination patterns to docs/meta-patterns/worktree-coordination/${NC}"
fi

# Copy CLAUDE.md templates
echo "Copying CLAUDE.md templates..."

# Root CLAUDE.md (only if doesn't exist - don't overwrite custom configs)
if [[ ! -f "$TARGET_DIR/CLAUDE.md" ]]; then
    # Get project name from directory
    PROJECT_NAME=$(basename "$TARGET_DIR")
    REPO_PATH="$TARGET_DIR"

    # Create from template with substitutions
    sed -e "s|{{PROJECT_NAME}}|$PROJECT_NAME|g" \
        -e "s|{{REPO_PATH}}|$REPO_PATH|g" \
        -e "s|{{PRINCIPLE_1_NAME}}|YOUR_PRINCIPLE_1|g" \
        -e "s|{{PRINCIPLE_1_DESC}}|TODO: describe your first design principle|g" \
        -e "s|{{PRINCIPLE_2_NAME}}|YOUR_PRINCIPLE_2|g" \
        -e "s|{{PRINCIPLE_2_DESC}}|TODO: describe your second design principle|g" \
        -e "s|{{PRINCIPLE_3_NAME}}|YOUR_PRINCIPLE_3|g" \
        -e "s|{{PRINCIPLE_3_DESC}}|TODO: describe your third design principle|g" \
        -e "s|{{TERM_1}}|your_term|g" \
        -e "s|{{TERM_1_ALT}}|alternate_name|g" \
        "$SCRIPT_DIR/templates/CLAUDE.md.root" > "$TARGET_DIR/CLAUDE.md"
    echo -e "  ${GREEN}Created: CLAUDE.md${NC}"
    echo -e "  ${YELLOW}  → Customize design principles and terminology in CLAUDE.md${NC}"
else
    echo -e "  ${YELLOW}Skipped: CLAUDE.md (already exists)${NC}"
fi

# Scripts CLAUDE.md
if [[ ! -f "$TARGET_DIR/scripts/CLAUDE.md" ]] && [[ -d "$TARGET_DIR/scripts" ]]; then
    cp "$SCRIPT_DIR/templates/CLAUDE.md.scripts" "$TARGET_DIR/scripts/CLAUDE.md"
    echo -e "  ${GREEN}Created: scripts/CLAUDE.md${NC}"
fi

# Tests CLAUDE.md
if [[ ! -f "$TARGET_DIR/tests/CLAUDE.md" ]] && [[ -d "$TARGET_DIR/tests" ]]; then
    cp "$SCRIPT_DIR/templates/CLAUDE.md.tests" "$TARGET_DIR/tests/CLAUDE.md"
    echo -e "  ${GREEN}Created: tests/CLAUDE.md${NC}"
fi

# docs/adr/CLAUDE.md (only in full mode)
if [[ "$MODE" == "--full" ]] && [[ ! -f "$TARGET_DIR/docs/adr/CLAUDE.md" ]]; then
    cp "$SCRIPT_DIR/templates/CLAUDE.md.docs-adr" "$TARGET_DIR/docs/adr/CLAUDE.md"
    echo -e "  ${GREEN}Created: docs/adr/CLAUDE.md${NC}"
fi

echo ""
echo -e "${GREEN}Installation complete!${NC}"
echo ""
echo "Next steps:"
echo "  1. Edit meta-process.yaml to configure patterns"
echo "  2. Customize design principles and terminology in CLAUDE.md"
if [[ "$MODE" == "--full" ]]; then
echo "  3. Add project-specific mappings to scripts/doc_coupling.yaml"
echo "  4. Run 'make status' to verify setup"
else
echo "  3. Run 'make status' to verify setup"
fi
echo ""
echo "Quick start:"
echo "  git checkout -b plan-N-description  # Create feature branch"
echo "  # ... do work ..."
echo "  make pr-auto-check && make pr-auto  # Non-interactive ship"
echo "  # or: make pr-ready && make pr      # Interactive ship"
