#!/usr/bin/env python3
"""Refuse a turn that asserts a verification nothing in it could support.

The predecessor of this gate was switched off on 2026-09-04: "string-matched
prose to infer semantics; false blocks and false passes both confirmed". It
decided whether a report claimed verification by running roughly fifteen regexes
over the assistant's own English -- behaviour words against evidence words,
first-person constructions, certainty adverbs, sentence-level vetoes. That cannot
distinguish a claim from a receipt, because "all tests pass" and "3 passed, 1
failed" are both prose containing the word "pass".

Policy `no-prose-string-matching` now forbids that, and this is the rebuild. The
split is the point:

  * **Evidence is read structurally.** What ran in this turn comes from the
    transcript's tool-use blocks and their results, which are JSON, and from the
    command line, which has a grammar. `git diff` shows text; `pytest` makes
    something happen. Classifying `Bash` wholesale is what made the predecessor
    silent on its own motivating incident, where five `git diff` reads preceded
    "I have verified it is correct" and 27 tests then failed. That classifier is
    kept verbatim -- it was never the broken half.

  * **The claim is read by a model.** Whether a report asserts a verification is
    a question about meaning, so it goes to a light LLM: `claude-code/haiku` on
    Claude Code, `codex/gpt-5.6-luna` on Codex. No regex touches the assistant's
    prose anywhere in this file.

Cost is bounded by asking only when the answer can matter. A turn that executed
something is allowed without a model call, because the overwhelmingly common
case is a claim backed by the thing that just ran. The call happens only on a
turn that executed nothing at all, which is where the failure lives.

Fails open, deliberately and loudly. A gate that hard-blocks on an API blip is
worse than the defect it prevents, and the predecessor's disabling is the
evidence: a gate that annoys gets switched off, and then nothing checks anything
for two days. An adjudication that could not run is recorded as `NOT_CHECKED`
and the turn proceeds.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from hook_receipts import start_hook_invocation
except ModuleNotFoundError:  # loaded outside its directory by importlib in tests
    start_hook_invocation = None  # type: ignore[assignment]

HOOK_NAME = "assertion-evidence-gate"
HOOK_VERSION = "2"

# Tool results can be enormous, and only a prefix is ever needed.
MAX_EVIDENCE_CHARS_PER_ITEM = 20_000
# What the adjudicator is shown of the report. Long enough for a closeout.
MAX_REPORT_CHARS = 12_000

# One judge call per qualifying turn. Haiku answered the motivating example
# correctly in a smoke test on 2026-09-06 for a fraction of a cent.
JUDGE_BUDGET_USD = 0.05
JUDGE_MODELS = {
    "claude-code": "claude-code/haiku",
    "codex": "codex/gpt-5.6-luna",
}
JUDGE_JUSTIFICATION = (
    "cheapest allowlisted judge for a per-turn gate; a one-sentence verdict does "
    "not need the default route"
)

INSPECTING_TOOLS = frozenset({"Read", "Grep", "Glob", "NotebookEdit", "Edit", "Write"})
# Bookkeeping. Observes nothing, backs nothing.
NON_EVIDENCE_TOOLS = frozenset({"TodoWrite", "ExitPlanMode", "AskUserQuestion"})
# Tools that carry an assertion to another actor. Their prompt is prose the
# assistant is asserting, so it is read for claims -- and the delegation itself
# can never be the evidence for the verdict it carries.
DELEGATING_TOOLS = frozenset({"Task", "Agent", "SendMessage"})
# Everything else -- Bash included, but Bash only after its command is read --
# is treated as executing: it acts on something outside the model.


# --- what a Bash command actually did ----------------------------------------
# `Bash` is one tool name covering two entirely different acts. `git diff` shows
# text; `pytest` makes something happen. Classifying the tool wholesale made the
# hook silent on its own motivating incident, where the verdict "I have verified
# it is correct" rested on five `git diff` reads. The command decides the class.

# Splitting on these over-splits a quoted `|` or `;`. That is the safe
# direction: more segments can only turn an inspection into an execution, and
# an execution is what keeps the hook silent.
_SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||[;\n|]")

# A redirect that writes somewhere. `2>&1` and `2>/dev/null` are not writes;
# anything else that lands bytes on disk is an act, not a look.
_WRITE_REDIRECT_RE = re.compile(r"(?<![0-9<>&])>>?(?!\s*&)\s*(?!/dev/null\b)\S")

_ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# Wrappers that run something else. The wrapped command decides the class.
_WRAPPER_COMMANDS = frozenset(
    {"sudo", "env", "time", "command", "nohup", "exec", "nice", "stdbuf", "timeout", "xargs"}
)
_WRAPPER_OPERAND_RE = re.compile(r"^[\d.]+[smhd]?$")
# Shell bookkeeping that observes nothing and changes nothing outside the shell.
# `cd /repo && git diff` is a diff read, and treating the `cd` as an unknown
# command would have silenced the hook on exactly the idiom it exists to catch.
_NEUTRAL_COMMANDS = frozenset({"cd", "pushd", "popd", "export", "set", "true", ":"})

# Commands that only show what is already there.
_INSPECTING_COMMANDS = frozenset(
    {
        "cat", "head", "tail", "less", "more", "grep", "egrep", "fgrep", "rg", "ag",
        "ls", "stat", "wc", "file", "tree", "jq", "echo", "pwd", "basename", "dirname",
    }
)
# `git` is both: `git diff` reads history, `git push` changes the world.
_GIT_INSPECTING_SUBCOMMANDS = frozenset(
    {"diff", "log", "show", "status", "blame", "rev-parse", "ls-files"}
)
_FIND_ACTING_PREDICATES = frozenset({"-exec", "-execdir", "-delete", "-ok", "-okdir"})
_SED_PRINT_ONLY_RE = re.compile(r"^-[A-Za-z]*n[A-Za-z]*$")


def _git_subcommand(tokens: list[str]) -> str:
    """First non-option token after `git`, skipping `-C <path>` and `-c k=v`."""

    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        return token
    return ""


def _classify_command_head(head: str, rest: list[str]) -> str:
    if head == "git":
        subcommand = _git_subcommand(rest)
        return "inspected" if subcommand in _GIT_INSPECTING_SUBCOMMANDS else "executed"
    if head == "sed":
        options = [token for token in rest if token.startswith("-")]
        if any(option.startswith("-i") for option in options):
            return "executed"
        return "inspected" if any(_SED_PRINT_ONLY_RE.match(o) for o in options) else "executed"
    if head == "find":
        return "executed" if any(t in _FIND_ACTING_PREDICATES for t in rest) else "inspected"
    return "inspected" if head in _INSPECTING_COMMANDS else "executed"


def _classify_segment(segment: str) -> str:
    if _WRITE_REDIRECT_RE.search(segment):
        return "executed"
    try:
        tokens = shlex.split(segment)
    except ValueError:
        tokens = segment.split()
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if _ENV_ASSIGNMENT_RE.match(token):
            index += 1
            continue
        # `./script`, `../bin/thing`: running a file, whatever it is called.
        if token.startswith(("./", "../")):
            return "executed"
        head = token.rsplit("/", 1)[-1]
        if head in _NEUTRAL_COMMANDS:
            return "neutral"
        if head in _WRAPPER_COMMANDS:
            index += 1
            while index < len(tokens) and (
                tokens[index].startswith("-")
                or _ENV_ASSIGNMENT_RE.match(tokens[index])
                or _WRAPPER_OPERAND_RE.match(tokens[index])
            ):
                index += 1
            continue
        return _classify_command_head(head, tokens[index + 1 :])
    # Nothing but assignments and wrappers, or an unparseable fragment.
    return "executed"


def classify_bash_command(command: str) -> str:
    """"inspected" only when every segment of the command merely shows text.

    Unrecognised commands are "executed". The bias is deliberate: an unknown
    command counted as execution keeps the hook silent, and a hook that nags on
    a correct turn gets deleted.
    """

    if not isinstance(command, str) or not command.strip():
        return "executed"
    inspected = False
    for segment in _SEGMENT_SPLIT_RE.split(command):
        if not segment.strip():
            continue
        classification = _classify_segment(segment)
        if classification == "executed":
            return "executed"
        if classification == "inspected":
            inspected = True
    # Nothing but shell bookkeeping observed nothing, so it backs nothing;
    # "executed" is the silent answer and the safe one.
    return "inspected" if inspected else "executed"


def classify_tool(name: str, tool_input: Any) -> str:
    """Which evidence class one tool call produces."""

    if name in INSPECTING_TOOLS:
        return "inspected"
    if name == "Bash":
        command = tool_input.get("command") if isinstance(tool_input, dict) else None
        return classify_bash_command(command)
    return "executed"


# --- reading the turn --------------------------------------------------------


@dataclass
class Delegation:
    """Prose asserted into a delegate's prompt, with what had run before it.

    A delegation cannot be the evidence for the verdict it carries, and neither
    can its report, which has not arrived yet. Only what already ran when the
    call was made counts -- which is the exact shape of the incident this gate
    exists for.
    """

    prompt: str
    executed_before: bool


@dataclass
class Turn:
    """Everything observable in the most recent assistant turn."""

    texts: list[str] = field(default_factory=list)
    tool_names: list[str] = field(default_factory=list)
    delegations: list[Delegation] = field(default_factory=list)
    executed: list[str] = field(default_factory=list)
    inspected: list[str] = field(default_factory=list)

    @property
    def has_executed(self) -> bool:
        return any(item.strip() for item in self.executed)


def _flatten(value: Any, budget: int = MAX_EVIDENCE_CHARS_PER_ITEM) -> str:
    """Render an arbitrary tool input or result as text."""

    if value is None:
        return ""
    if isinstance(value, str):
        return value[:budget]
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        return " ".join(_flatten(item, budget) for item in value.values())[:budget]
    if isinstance(value, list):
        return " ".join(_flatten(item, budget) for item in value)[:budget]
    return str(value)[:budget]


def _is_tool_result(event: dict[str, Any], content: Any) -> bool:
    if event.get("toolUseResult") is not None:
        return True
    if isinstance(content, list):
        return any(
            isinstance(block, dict) and block.get("type") == "tool_result" for block in content
        )
    return False


def _is_user_turn_boundary(event: dict[str, Any]) -> bool:
    """True for a message the human actually sent, not a tool result or a hook."""

    if event.get("type") != "user" or event.get("isSidechain") or event.get("isMeta"):
        return False
    message = event.get("message")
    if not isinstance(message, dict):
        return False
    content = message.get("content")
    if _is_tool_result(event, content):
        return False
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        return any(
            isinstance(block, dict) and block.get("type") in {"text", "image"} for block in content
        )
    return False


def read_events(transcript_path: str) -> list[dict[str, Any]]:
    """Parse a Claude Code JSONL transcript, skipping lines that are not objects."""

    events: list[dict[str, Any]] = []
    path = Path(transcript_path).expanduser()
    if not path.is_file():
        return events
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
    return events


def latest_turn(events: list[dict[str, Any]]) -> Turn:
    """Collect the assistant's text and every evidence item since the last user message."""

    start = 0
    for index, event in enumerate(events):
        if _is_user_turn_boundary(event):
            start = index + 1

    turn = Turn()
    result_class: dict[str, str] = {}

    for event in events[start:]:
        if event.get("isSidechain"):
            continue
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None

        if event.get("type") == "assistant" and isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                kind = block.get("type")
                if kind == "text":
                    text = block.get("text")
                    if isinstance(text, str) and text.strip():
                        turn.texts.append(text)
                elif kind == "tool_use":
                    name = str(block.get("name") or "")
                    if not name or name in NON_EVIDENCE_TOOLS:
                        continue
                    tool_input = block.get("input")
                    turn.tool_names.append(name)
                    if name in DELEGATING_TOOLS:
                        prompt = tool_input.get("prompt") if isinstance(tool_input, dict) else None
                        if isinstance(prompt, str) and prompt.strip():
                            turn.delegations.append(
                                Delegation(prompt=prompt, executed_before=turn.has_executed)
                            )
                    rendered = f"{name} {_flatten(tool_input)}"
                    kind_of = classify_tool(name, tool_input)
                    (turn.inspected if kind_of == "inspected" else turn.executed).append(rendered)
                    identifier = block.get("id")
                    if isinstance(identifier, str):
                        result_class[identifier] = kind_of
            continue

        if event.get("type") != "user":
            continue

        rendered = _flatten(event.get("toolUseResult")) + " " + _flatten(content)
        if not rendered.strip():
            continue
        kind_of = None
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    kind_of = result_class.get(str(block.get("tool_use_id")))
                    break
        if kind_of is None:
            # No matching call in this turn: a subagent report, a background-task
            # notification, CI output, something the human pasted. It executed
            # somewhere, so it counts as executed.
            #
            # The predecessor decided this by regexing the text for "the
            # signature of something having actually run". That is prose
            # matching, and it is now forbidden. Counting it as executed is the
            # conservative direction: it can only make this gate quieter, never
            # make it block a turn it should not.
            kind_of = "executed"
        (turn.inspected if kind_of == "inspected" else turn.executed).append(rendered)

    return turn


# --- adjudication ------------------------------------------------------------


class Verdict:
    """The judge's answer, or the fact that it could not be obtained."""

    def __init__(self, *, checked: bool, asserts: bool, quote: str, why: str, reason_code: str):
        self.checked = checked
        self.asserts = asserts
        self.quote = quote
        self.why = why
        self.reason_code = reason_code


JUDGE_INSTRUCTIONS = """You are a gate on an AI coding agent's final report.

The agent's turn executed NOTHING. Every tool call in it only read or displayed
existing text: no test run, no build, no script, no deploy, nothing that could
demonstrate behaviour.

Decide one thing: does the report assert, as established fact, that something
works, passes, is correct, is fixed, or is verified?

Say yes only for an assertion the agent presents as its own finding. Say no for:
- relaying a result that arrived from elsewhere (a subagent, CI, the human)
- a plan, an intention, a proposal, a question, a hypothetical
- describing what a file says, which reading can support
- an explicitly hedged or unverified statement ("I have not run it", "untested")
- a claim about the code's content rather than its behaviour

If yes, quote the exact sentence, verbatim, from the report.
"""


def _judge_model(client: str) -> str:
    return JUDGE_MODELS.get(client, JUDGE_MODELS["claude-code"])


def adjudicate(report: str, inspected: list[str], client: str, session_id: str) -> Verdict:
    """Ask a light LLM whether the report asserts a verification nothing backs.

    Every failure here returns `checked=False`. A gate that blocks a turn because
    a provider had a bad minute is a gate that gets switched off, and the
    predecessor being off for two days is what that costs.
    """

    try:
        from llm_client import call_llm_structured
        from pydantic import BaseModel, Field
    except Exception as exc:  # noqa: BLE001 - any import problem means no judgement
        return Verdict(
            checked=False, asserts=False, quote="", why=str(exc), reason_code="judge_unavailable"
        )

    class _Answer(BaseModel):
        asserts_unbacked_verification: bool = Field(
            description=(
                "True only if the report states as established fact that something works, "
                "passes, is correct, is fixed, or is verified, as the agent's own finding."
            )
        )
        quote: str = Field(
            description="The exact sentence from the report, verbatim, or an empty string."
        )
        why: str = Field(description="One sentence explaining the decision.")

    inspected_summary = "\n".join(item[:400] for item in inspected[:20]) or "(nothing at all)"
    prompt = (
        f"{JUDGE_INSTRUCTIONS}\n\n"
        f"--- what the turn only READ ---\n{inspected_summary}\n\n"
        f"--- the report ---\n{report[:MAX_REPORT_CHARS]}\n"
    )

    try:
        answer, _result = call_llm_structured(
            _judge_model(client),
            [{"role": "user", "content": prompt}],
            _Answer,
            task="assertion-evidence-gate",
            trace_id=f"aeg-{session_id}",
            max_budget=JUDGE_BUDGET_USD,
            model_justification=JUDGE_JUSTIFICATION,
        )
    except Exception as exc:  # noqa: BLE001 - fail open, loudly, never silently
        return Verdict(
            checked=False,
            asserts=False,
            quote="",
            why=f"{type(exc).__name__}: {exc}",
            reason_code="judge_failed",
        )

    return Verdict(
        checked=True,
        asserts=bool(answer.asserts_unbacked_verification),
        quote=answer.quote.strip(),
        why=answer.why.strip(),
        reason_code="unbacked_assertion" if answer.asserts_unbacked_verification else "backed",
    )


# --- hook --------------------------------------------------------------------


def _deny(message: str) -> str:
    return json.dumps({"decision": "block", "reason": message})


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    client = "codex" if "--agent" in argv and "codex" in argv else "claude-code"

    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict):
        return 0

    # A Stop hook that refuses a re-fire can refuse forever. Required by
    # project-meta's check_blocking_gates.
    if payload.get("stop_hook_active") is True:
        return 0

    session_id = str(payload.get("session_id") or "unknown")
    invocation = None
    if start_hook_invocation is not None:
        try:
            invocation = start_hook_invocation(
                hook_name=HOOK_NAME,
                hook_version=HOOK_VERSION,
                script_path=Path(__file__),
                payload=payload,
            )
        except Exception as exc:  # noqa: BLE001 - receipts must never break the turn
            print(f"{HOOK_NAME}: receipt not started: {exc}", file=sys.stderr)
            invocation = None

    def finish(decision: str, reason_code: str) -> None:
        if invocation is not None:
            try:
                invocation.complete(decision=decision, reason_code=reason_code)
            except Exception as exc:  # noqa: BLE001 - never swallowed, never fatal
                print(f"{HOOK_NAME}: receipt not completed: {exc}", file=sys.stderr)

    transcript = payload.get("transcript_path")
    if not isinstance(transcript, str) or not transcript:
        finish("allow", "no_transcript")
        return 0

    turn = latest_turn(read_events(transcript))

    # The cheap path, and the common one. Something ran; the claim has something
    # to rest on. No model call.
    if turn.has_executed:
        finish("allow", "turn_executed_something")
        return 0

    report = "\n\n".join(turn.texts)
    for delegation in turn.delegations:
        if not delegation.executed_before:
            report += "\n\n" + delegation.prompt
    if not report.strip():
        finish("allow", "no_report")
        return 0

    verdict = adjudicate(report, turn.inspected, client, session_id)

    if not verdict.checked:
        finish("warn", verdict.reason_code)
        print(
            json.dumps(
                {
                    "systemMessage": (
                        "assertion-evidence gate NOT_CHECKED: the adjudicator could not run "
                        f"({verdict.why}). Nothing was judged, so nothing is cleared."
                    )
                }
            )
        )
        return 0

    if not verdict.asserts:
        finish("allow", "backed")
        return 0

    finish("block", "unbacked_assertion")
    quoted = f"\n\n  {verdict.quote}" if verdict.quote else ""
    print(
        _deny(
            "This turn executed nothing -- every tool call in it only read or displayed "
            f"existing text -- and the report asserts a verification anyway.{quoted}\n\n"
            f"{verdict.why}\n\n"
            "Run the thing that would show it, or say plainly what you did not verify."
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
