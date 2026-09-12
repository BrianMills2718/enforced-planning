# Plan 135 native-v2 eval decision sign-off — round 1

**Decision:** Retain the correction-learning classifier in manual/off mode; do
not promote native launching or blocking.

**Eval:** `prompts/correction_learning/native_corpus_v2.json` and
`native_result_v2.json` at `7f35f22ddaf86bdfbcb3e12d276808ebd9c3f1f3`.

**Verdict: REJECTED.**

1. **Validity: FAIL.** Fresh positive and negative controls passed in one Sonnet
   call (7.098 seconds, zero errors, `$0.00`). The loader resolved 128/128 cases;
   focused tests and `scripts/self_test.py` passed. The retained 22-call trace
   had zero errors/retries/tools, 691.101 seconds latency, and `$0.00` observed
   subscription cost. However, `native_result_v2.json` records a nonexistent
   manually expanded source revision instead of the actual corpus commit.
2. **Representativeness: FAIL.** The two candidate waves are immutable,
   disjoint, and exactly union to the corpus, but the privacy-reduced annotation
   records and an executable source-ranking reproduction were not retained.
   Agreement, adjudication, and the claim that the sources were hash-ranked
   therefore could not be independently recomputed.
3. **Diagnosis: PASS.** Inspection of all eight unacceptable adjacent pairs
   supports the class diagnosis: imperative continuation/resumption corrections
   were missed; terse clarification questions produced the false positive and
   ambiguous non-correction verdicts. Exact extraction separates these from
   admission failures.
4. **Generalization: N/A.** No post-result mechanism fix or replay occurred.
5. **Decision: FAIL.** Manual/off remains the safety default, but the eval cannot
   validate that decision while validity and representativeness evidence are
   broken.

Required fixes: reconcile the recorded revisions to real Git objects without
altering or replaying the holdout; preserve privacy-reduced annotator and
adjudication records; retain executable selection/ranking evidence; rerun fresh
adversarial sign-off.
