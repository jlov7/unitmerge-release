# Limitations

The configuration workflow combines mechanical edits and records explicit
choices. Optional local Draft 2020-12 validation checks only the supplied schema;
it does not establish business correctness, credentials, deployment compatibility
or semantic correctness. Without the extra and a supplied schema no schema check
runs. External references and `$id` are refused; `format` is informational.
Local schemas are trusted for computational cost, including regex evaluation.
Arrays require a whole-side choice when both changed differently unless an
explicit keyed policy applies. Keyed arrays require unique nonempty string IDs,
merge whole entries and sort by ID. This loses input ordering and is unsuitable
for order-sensitive arrays. Input bytes must remain unchanged after
review. Hashes are unsigned: replacing a complete bundle is outside their trust
boundary. Output verification detects byte/content mismatch relative to its
supplied receipt; it cannot authenticate a replaced consistent pair or prove
schema validation happened. Reports and text review retain/disclose source
values and require the same privacy treatment.
The two output files are exclusively created but do not form an atomic
transaction across a process or machine crash. Its local authored task and
reference matrix establish software behavior, not customer adoption or an
independent human-usefulness result.

This artifact can check receipt bytes and collate declared proposals. It cannot establish source authenticity, truth, semantic entailment, independence or a winner among conflicting values. The caller can fabricate current flags, worker IDs, quotes and registry entries. A matching quote is an integrity check within caller-supplied bytes.

The candidate and simple normalized union tie in the supplied comparisons. The package is not a complete implementation or performance reproduction of UnitBoost. All seven software examples are authored; the SQuAD pilot is a small selected, exposed development subset using deterministic extractors. Benchmark labels are independent of those extractors, but their scores are not broad external validation.

Original real-system integration, residual-directed worker execution, LLM comparisons, a semantic validator, preregistered independent holdout and human usefulness study remain NOT RUN. Software tests, packaging and automated reviews do not substitute for those milestones. No production, security-certification or adoption claim is made.

The CLI bounds local JSON ingestion. The checked API bounds proposal count and source bytes. Direct structural-only library calls have no general resource-isolation promise. Do not process arbitrary unbounded in-memory data or sensitive files without your own application boundary.

No network service, provider adapter, account or API key is required.
