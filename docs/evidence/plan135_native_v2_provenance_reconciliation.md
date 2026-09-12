# Plan 135 native-v2 provenance reconciliation

This record repairs evidence references only. It does not alter the frozen
corpus, prompt, labels, result, thresholds, or classifier output, and the
128-case holdout was not replayed.

## Revision correction

The run argument and retained result record
`65f20a8e2c2314cbb691aa7c25da1a67a85c8374`; that object does not exist. The
actual frozen-corpus commit is
`65f20a8bbe81063410921c2ad628df2e3e2af4fc`. At that commit:

- `native_corpus_v2.json` hashes to
  `89dff34de2feb7703e96e2dc08efda2845c8c5a7a3ff4cb2291fc5e5a0100f7e`,
  exactly the corpus hash retained in the result;
- `classify.yaml` hashes to
  `be733d78457f18bb856229bbf852b0b5c01b2eea3385870066b11e18f7959b19`,
  exactly the prompt hash retained in the result.

The candidate artifacts similarly record the nonexistent abbreviation
`f5680f700c4a`. The actual prompt/admission repair commit is
`f5680f7df4088ab2b4336e869c81d79f5664d2b8`; Git confirms `classify.yaml` is
byte-identical between that commit and the frozen-corpus commit. The durable
trace prefix retains the typo-derived segment
`correction-learning/native-v1/65f20a8e2c23/`; it is a unique lookup key, not a
Git revision.

## Annotation reconstruction

The six adjacent privacy-reduced annotation artifacts retain every event ID and
label plus the SHA-256 of the original blind annotation file. They intentionally
omit raw conversation prose and rationales. Joining annotator A and B by event
ID and using the relevant adjudication record only on disagreements recomputes:

- 128 cases: 14 corrections, 113 non-corrections, one ambiguous;
- 120 agreements and eight disagreements;
- eight adjudicated labels;
- exact equality with every final label in `native_corpus_v2.json`.

Recompute this with
`python3 docs/evidence/plan135_native_v2_annotation_check.py`.

## Selection reconstruction

Run `python3 docs/evidence/plan135_native_v2_selection.py` from the repository
root. It reconstructs the complete eligible-source ranking, rank windows, and
event windows from native metadata, and byte-compares both committed candidate
artifacts. The verified hashes are:

- initial wave:
  `8f588eb03e1fba2924d682c87b5e920bb38eb78ced5f492680737084c90ac30d`;
- extension wave:
  `8ab49c7bddc901f822091e69f2c2ba50a8e7cdf99488a6615fa8d78790d248d7`.
