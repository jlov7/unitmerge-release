# Evaluation

## Authored regression and comparison track

`python -m unittest discover -s tests -v` with the installed package exercises malformed inputs, canonical identity, conflicts, stale sources, constraints, byte receipts and evaluator regressions. `scripts/verify_release.py` repeats the full suite against a wheel built from the source distribution with isolated imports. Source and installed runs are separate software checks, not independent scientific replication.

`experiments/cases.json` is a frozen set of seven authored cases. `experiments/compare.py` replays all three arms over identical eligible proposals, producing 21 records. Every candidate failure, unresolved output and joint violation stays in the denominator. It includes duplicated origins, bad quotes, a matching quote with a wrong value and an inconsistent row. CPU timings are illustrative, not a performance benchmark.

## SQuAD 2.0 development pilot

The independently annotated dataset supplies answer and answerability labels. It does not validate UnitMerge as a method, source authenticity or semantic truth. The frozen protocol selects the first 32 matching numeric/date questions using input text only. Two rule-based extractors share source context; neither sees labels. Both arms and the fixed worker receive identical eligible proposals.

| Arm | Exact match | Token F1 | Proposed on answerable | False answer on unanswerable | Conflict / unsupported |
| --- | --- | --- | --- | --- | --- |
| Checked collation | 13/32 | 0.40625 | 10/19 | 8/13 | 2 / 12 |
| Normalized union | 13/32 | 0.40625 | 10/19 | 8/13 | 2 / 12 |
| Fixed worker w1 | 13/32 | 0.40625 | 12/19 | 8/13 | 0 / 12 |

All 96 arm-case records are in `experiments/squad-pilot-v1.results.json`. They contain identifiers, source/prediction digests, statuses and metrics, not passage, question, quote or answer text. Checked collation and union have identical statuses, prediction hashes and scores. Conflict is not an intentional abstention policy. Empty predictions use SQuAD's unanswerable convention.

The original protocol and result bytes are preserved, including their historical rights-review wording. Current redistribution terms and attribution are in [NOTICE](../NOTICE). No raw dataset is bundled.

## Reproduce external-label scoring

Acquire the official development JSON yourself under its terms. No helper downloads it. From an installed source distribution:

```sh
uv run --no-project python experiments/squad_compare.py --corpus PATH_TO_DEV_V2_JSON
```

The runner rejects files over 8 MiB or whose SHA-256 differs from `80a5225e94905956a6446d296ca1093975c4d3b3260f1d6c8f68bc2ab77182d8`. The exact selection, extractors, arms and scoring are fixed in `experiments/squad-protocol-v1.json`. Tests use authored fixtures and need no corpus or network.

These 32 questions are exposed development data. Do not tune on them and describe a rerun as a fresh holdout. No answer-quality advantage was found. The reusable result is the checked contract and a falsifiable negative comparison. Real model, independent holdout, production integration and human-usefulness evaluations remain NOT RUN.
