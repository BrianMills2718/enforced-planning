# Background Coding-Agent Runtime Landscape

**Reviewed:** 2026-07-16
**Decision:** How should a coordination mailbox start a quiet, bounded Codex
worker without requiring a human to relay or operate an interactive TUI?
**Recommendation confidence:** Medium-high for the first adapter; medium for the
long-term runtime because the app-server surface is still evolving.

## Scope

This comparison covers the execution boundary after a request is authorized and
queued. It does not choose the mailbox, planning authority, personal-agent
runtime, or organization-wide scheduler.

## Sources, Observations, And Implications

| Source | Observation | Project implication |
|--------|-------------|---------------------|
| [OpenAI non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode) | `codex exec` is the documented non-interactive surface for scripts and CI, with structured output and resumable sessions. | Use it as the first stable worker adapter behind a small dispatcher. |
| [Official Codex app-server README](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md) | App-server exposes long-lived JSON-RPC threads, turns, approvals, and server notifications. | Preserve a runtime adapter boundary so a later daemon can reuse sessions and stream events. |
| [Codex issue #25552](https://github.com/openai/codex/issues/25552) | Users report documentation and protocol drift around app-server methods. | Do not make the first demo depend on a fast-moving protocol without compatibility tests. |
| [Codex issue #24542](https://github.com/openai/codex/issues/24542) | A daemon/proxy integration report shows process and transport conflicts can occur in long-lived setups. | Treat daemon ownership, restart, and collision behavior as explicit operational work. |

## Alternatives

| Option | Strengths | Weaknesses | First usable effort | Lock-in |
|--------|-----------|------------|---------------------|---------|
| Bounded `codex exec` per request | Documented, process-isolated, easy logs/exit codes, simple recovery | Startup cost; session continuity requires explicit resume state | 0.5-1 day | Low |
| Long-lived Codex app-server | Native threads, event streaming, approvals, lower repeated startup overhead | Experimental/evolving protocol; daemon lifecycle and compatibility burden | 2-5 days for a defended adapter | Medium, contained by adapter |
| Lifecycle hooks only | Cheap notification and context injection into active sessions | Cannot reliably start an idle worker; tied to client lifecycle | Hours | Medium |
| Custom queue plus generic subprocess worker | Clear leases, retries, concurrency, and observability | More infrastructure; still needs a concrete agent runtime | 1-3 days | Low |
| Hermes as coding-worker runtime | Channels, scheduling, memory, and long-lived agent behavior already exist | Broad runtime for a narrow coding task; duplicates Codex execution semantics and expands operational surface | 2-7 days to integrate responsibly | Medium-high |

Effort ranges are engineering estimates for this repository's current mailbox,
not claims from the cited sources.

## Recommendation

1. Start with a bounded dispatcher that claims one authorized request, launches
   `codex exec`, retains stdout/stderr/exit status and the resulting session ID,
   and acknowledges only after the worker records a disposition.
2. Put execution behind a provider-neutral worker adapter. The mailbox and plan
   contracts must not depend on `codex exec` command syntax.
3. Add an app-server adapter only when retained thread continuity, lower startup
   latency, or event streaming has demonstrated value that exceeds its daemon
   and protocol-compatibility cost.
4. Keep hooks as delivery accelerators for already-active sessions, not as the
   worker-start mechanism.
5. Use Hermes for personal-agent channels, memory, recurring behavior, and
   actions where those capabilities are actually required; do not introduce it
   solely to run a bounded coding request.

## Reuse And Differentiation

- **Reuse:** Codex's documented non-interactive execution, structured output,
  session resume, and later app-server thread protocol.
- **Build:** a small mailbox lease/dispatcher and an execution adapter because
  request authority, claims, and acknowledgements are ecosystem-specific.
- **Do not duplicate:** model loops, shell tooling, approval semantics, or
  conversation persistence already owned by the selected agent runtime.
- **Differentiation:** governed request authority and evidence-backed completion,
  not a new general-purpose agent harness.

## Uncertainty

- Real startup latency and concurrent-worker behavior have not yet been measured
  on the target host.
- App-server stability may improve enough to change the preferred first adapter.
- A production dispatcher needs explicit lease expiry, retry, cancellation, and
  secret-boundary decisions; those are not required to choose the first runtime.

## Refresh Trigger

Refresh this comparison before implementing the dispatcher if OpenAI declares
app-server stable, if `codex exec` loses required structured/resume behavior, or
if measured startup latency prevents the target workflow. Otherwise review by
2026-10-16.
