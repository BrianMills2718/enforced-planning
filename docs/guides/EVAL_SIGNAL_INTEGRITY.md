# Eval Signal Integrity — the loop's compass must be trustworthy

Canonical loop-engineering doctrine. Companion to `CONTINUOUS_EXECUTION_CONTRACT.md`
(that doc defines *when a loop stops*; this one defines *whether the loop's
steering signal can be trusted at all*). When a repo's CLAUDE.md or a skill
references this doc, the rules here are authoritative.

## The principle

An autonomous loop steers on a feedback signal — an eval / benchmark / metric
tells it **keep going · kill · ship · tune more**. A loop is only as trustworthy
as the *fidelity of that signal*. If the number is decoupled from real
capability, every decision downstream is **confidently** wrong, and the loop will
not self-correct — it drives harder in the wrong direction. So the eval is not a
step in the loop; it is the loop's **compass**, and a corrupted compass is worse
than none.

## The failure is one axis, two directions (Goodhart)

Both are "**the number ≠ the real capability**":

| | Number is… | You wrongly… | Cause |
|---|---|---|---|
| **Benchmark-before-it-works** (false-kill) | artificially **LOW** | **abandon** a good approach | the system-under-test was not actually running (unbuilt deps/indexes, partial build) |
| **Eval gaming / overfit** | artificially **HIGH** | **ship/trust** a bad approach | the fix was tuned to the specific cases, not the capability |

The "false-kill gate" (a kill decision produced by an unbuilt system scoring ~0)
and "benchmark gaming" (tuning resolvers to memorized test cases) are the **same
disease** in opposite signs. Real example (2026-07-07, DIGIMON): a kill/continue
gate could retire the graph-retrieval investment because the VDBs were unbuilt
and the graph partial — graph scored "unavailable," which the gate could read as
"graph adds no value." The same repo had *also* been bitten on the high side
(Plan #72 de-gaming). Same team, both signs → the failure is structural.

## The five validity gates (the process)

An eval readout is actionable only if it passes these, in order:

1. **Validity gate (pre-run)** — a **positive control** (a known-good case the
   system MUST pass, proving it can produce a right signal at all) **+ a
   build-adequacy precondition** (every component the eval depends on is actually
   built and reachable). Everyone remembers negative controls (rejects noise);
   the positive control is the missing twin. **`unavailable ≠ zero`**: a
   missing/partial component makes the run **INVALID / inconclusive**, never a low
   score a gate can act on.
2. **Representativeness gate (eval design)** — the eval set is representative and
   has **held-out cases per failure class**; it is NOT curated to the questions
   you already wrote (hand-picking the corpus that answers your questions removes
   distractors and seeds gaming).
3. **Diagnosis gate (on a subpar result)** — the WHY is stated at the level of a
   **class of input**, not the failing instance ("temporal-contrast questions
   fail because the retriever can't align two dated chunks," not "Q6 is wrong").
   No class-level why → no fix.
4. **Generalization gate (the fix)** — the fix targets the **class mechanism** and
   must clear three checks: (a) it fixes *held-out* cases of the same class
   (generalizes), (b) it does not regress other classes, (c) the gain survives a
   *fresh* eval the fix never saw. If it only moves the cases you looked at, it is
   overfitting = gaming → reject it. **You may not tune against the test you are
   graded on.**
5. **Decision gate** — kill/continue/ship fires **only** on a valid run (1) with a
   generalizing fix (4). Never on instance-patching; never on an invalid run.

The through-line agents collapse (and must not): *is the signal real?* (1,2) →
*what does it tell me?* (3) → *did my fix earn a real gain or a fake one?* (4).

## The trust mechanism: independent adversarial sign-off

Gates 1–5 are self-checks — and self-attestation is the same "trust the readout"
bug one level up. So an eval-driven decision is **not valid without an independent
sign-off**:

- **Independent:** fresh context, did not run the loop; ideally a different
  agent/model. Gets the decision + evidence, nothing else.
- **Adversarial, not confirmatory:** prompt = *"try to prove the loop was NOT
  honestly followed; sign off only if you fail."* ("Check this looks good"
  rubber-stamps; "refute this" finds holes.)
- **Verify by execution, per gate:** re-run the positive control; confirm the
  deps/indexes exist; confirm the held-out set was truly held out; **re-run the
  eval and confirm the gain reproduces** on unseen cases; check the fix targets
  the class, not the instances. Reading the loop-agent's claims is banned.
- **Gates the decision:** the decision does not take effect without a sign-off
  artifact — not "warn and hope."
- **Evidence-backed:** the signer emits command+output proof each gate held, so
  *"who signs off the signer?"* bottoms out not in another opinion but in
  reproducible output a human can spot-check. The buck stops at
  execution-grounded evidence + human direction.

Procedure: the `eval-decision-signoff` skill.

## One-line statement

**Never let an autonomous loop steer on an unvalidated signal — in either
direction — and never let it self-certify that it validated.**
