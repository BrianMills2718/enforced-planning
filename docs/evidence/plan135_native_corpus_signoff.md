# Plan 135 native-corpus eval decision sign-off

**Decision:** Retain the correction-learning classifier in manual/off mode; do
not promote native launching or blocking.

**Eval:** `prompts/correction_learning/native_result_v1.json` at
`85095b1cc33c980b3cde4ad0c8b386561b0825ab` (replay source
`ce5dfff176ac248f2f31d60ac871c9341b5093c0`).

**Verdict: REJECTED.**

1. **Validity: PASS.** Fresh Sonnet controls correctly classified the known
   positive and negative in 6.393 seconds. Observability contains exactly three
   original replay calls, all successful with 28.381, 21.545, and 8.521 second
   latency and no error. Exact native provenance resolved 14/14 events. Focused
   tests passed (39 passed, 1 skipped), and `scripts/self_test.py` passed.
2. **Representativeness: FAIL.** Re-extraction disproved the declared “every
   post-pilot exchange” population. Session `01a09110-…` contains seven
   post-cutoff exchanges, but the manifest includes six; omitted event
   `c8005076ef88be8189d52e1f` occurred before corpus freeze and before later
   included events. Independent semantic inspection also found two
   decision-bearing labels inconsistent or materially contestable under the
   prompt’s adjacent-exchange contract: `cx-brain-01` relies on information
   revealed after the labeled user event, while `cx-aes-03` contains explicit
   process challenges that plausibly satisfy the correction definition.
3. **Diagnosis: FAIL.** The artifact reports instance counts but no trustworthy
   class-level mechanism. It does not separate classifier error from mislabeled
   scored cases or from the extraction layer admitting host protocol messages
   as user conversation.
4. **Generalization: N/A.** No fix was applied after corpus freeze. Git ancestry
   confirms corpus freeze `2434017` preceded replay `ce5dfff`; corpus and prompt
   remained byte-identical through `85095b1`.
5. **Decision: FAIL.** The conservative manual/off state remains appropriate
   because promotion criteria are unmet, but it cannot be signed off as an
   eval-driven decision when representativeness and diagnosis failed.

Required fixes: freeze a new corpus whose enumerated population matches its
selection rule; label it independently using only information available to the
classifier; resolve the two disputed labels; state class-level diagnoses that
distinguish extraction/protocol contamination from semantic-classifier errors;
then perform one fresh held-out replay and independent sign-off. Until then,
manual/off is the safety default, not a validated conclusion from this eval.
