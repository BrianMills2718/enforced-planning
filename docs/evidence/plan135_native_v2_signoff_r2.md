# Plan 135 native-v2 eval decision sign-off — round 2

**Decision:** Retain the correction-learning classifier in manual/off mode; do
not promote native launching or blocking.

**Eval:** frozen corpus/result at
`7f35f22ddaf86bdfbcb3e12d276808ebd9c3f1f3`; evidence repair at
`387a4e6d8ed81ffeb39dbc66b3f6b90e4d1f7a59`.

**Verdict: REJECTED.**

1. **Validity: PASS.** Fresh controls, exact 128-case loading, focused tests,
   self-test, observability, corrected Git ancestry, and frozen corpus/prompt
   hashes all passed. The evidence reconciliation is sufficient for the two
   mistakenly expanded revision strings.
2. **Representativeness: FAIL.** Selection reproduction and the 128-case
   candidate union passed. The privacy-reduced label files were committed only
   after the result, however, and the original blind files matching the
   pre-result hashes are not retained Git objects. The later rows are internally
   consistent with the frozen corpus but cannot independently prove historical
   blind annotation.
3. **Diagnosis: PASS.** Raw pairs support the imperative continuation/correction
   miss class and terse-question false-positive/ambiguity class.
4. **Generalization: N/A.** No classifier or holdout change/replay occurred.
5. **Decision: FAIL.** Manual/off remains the safety default, but v2 cannot
   validate the decision while blind-label history is unreproducible.

Disposition: do not retain raw annotation rationales merely to rescue the run;
that would violate the frozen privacy contract. Treat v2 as development data.
For the next unseen corpus, commit privacy-reduced A/B labels and adjudications
before classifier replay, then require fresh sign-off.
