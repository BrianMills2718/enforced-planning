#!/bin/bash
# Post-edit quiz — surfaces understanding questions after editing src/ files.
# PostToolUse/Edit hook — shows constraint quiz after successful edits.
#
# This is advisory (exit 0) — it doesn't block, just prompts engagement.
#
# Only triggers for src/ files with governance entries.

set -e

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null || echo "")
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null || echo "")

# Only fire after Edit and Write
if [[ "$TOOL_NAME" != "Edit" && "$TOOL_NAME" != "Write" ]]; then
    exit 0
fi

if [[ -z "$FILE_PATH" ]]; then
    exit 0
fi

# Only for src/ files
if [[ "$FILE_PATH" != *"/src/"* ]] && [[ "$FILE_PATH" != "src/"* ]]; then
    exit 0
fi

# Bypass
if [[ "${SKIP_QUIZ:-}" == "1" ]]; then
    exit 0
fi

# Get repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Normalize path
REL_PATH="$FILE_PATH"
if [[ "$FILE_PATH" == "$REPO_ROOT/"* ]]; then
    REL_PATH="${FILE_PATH#$REPO_ROOT/}"
fi
if [[ "$REL_PATH" == worktrees/* ]]; then
    REL_PATH=$(echo "$REL_PATH" | sed 's|^worktrees/[^/]*/||')
fi

# Find quiz script
QUIZ_SCRIPT="$REPO_ROOT/scripts/generate_quiz.py"
if [[ ! -f "$QUIZ_SCRIPT" ]]; then
    exit 0
fi

# Generate quiz (JSON mode for structured output)
QUIZ_STDERR_FILE=$(mktemp)
set +e
RESULT=$(cd "$REPO_ROOT" && python "$QUIZ_SCRIPT" "$REL_PATH" --json 2>"$QUIZ_STDERR_FILE")
QUIZ_EXIT=$?
set -e
QUIZ_CRASHED=0
grep -q '^Traceback' "$QUIZ_STDERR_FILE" && QUIZ_CRASHED=1
QUIZ_STDERR=$(tail -n 3 "$QUIZ_STDERR_FILE")
rm -f "$QUIZ_STDERR_FILE"

if [[ $QUIZ_EXIT -ne 0 && $QUIZ_CRASHED -eq 1 ]]; then
    # Advisory, so never block; but a crashed generator must not look like
    # "no questions for this file". Deliberate exits (2 = no relationships.yaml)
    # stay quiet.
    FAILURE_ESCAPED=$(printf 'post-edit quiz generator failed (exit %s) for %s: %s' "$QUIZ_EXIT" "$REL_PATH" "$QUIZ_STDERR" | jq -Rs .)
    printf '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":%s}}\n' "$FAILURE_ESCAPED"
    exit 0
fi

if [[ $QUIZ_EXIT -ne 0 ]] || [[ -z "$RESULT" ]] || [[ "$RESULT" == "[]" ]]; then
    exit 0
fi

# Extract just the questions as readable text
QUIZ_TEXT=$(cd "$REPO_ROOT" && python "$QUIZ_SCRIPT" "$REL_PATH" 2>/dev/null)

if [[ -z "$QUIZ_TEXT" ]]; then
    exit 0
fi

QUIZ_ESCAPED=$(echo "$QUIZ_TEXT" | jq -Rs .)

cat << EOF
{
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "additionalContext": $QUIZ_ESCAPED
  }
}
EOF

exit 0
