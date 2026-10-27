# Design

The configuration workflow in `reconcile.py` uses three exact JSON byte strings
and ordinary three-way equality rules. It recurses through objects, keeps
arrays atomic and represents missing members separately from null. Review and
resolution are separate calls. Resolution recomputes every review field from
the supplied originals, requires one source-side choice per conflict and
returns materialized JSON plus the chosen-path receipt. This is configuration
reconciliation, with no semantic winner or scoring claim. SHA-256 checks bind
caller-supplied bytes and do not authenticate the review or its author.

The data flow is explicit: caller registry and source bytes, receipt eligibility, deterministic collation, constraints, review output. `evidence.py` checks complete-source SHA-256 plus UTF-8 byte spans. `core.py` collates canonical JSON values by known unit and source IDs. `baselines.py` provides independent normalized union and a preselected worker. `cli.py` supplies bounded local JSON ingestion; `demo.py` demonstrates both successful receipts and counterexamples.

The structural contract is validated before receipt filtering. A malformed proposal cannot disappear merely because its receipt fails. Current/stale flags remain caller assertions. No source is fetched, no worker identity is authenticated and no citation is interpreted as an instruction.

Outputs sort unit IDs, alternatives and source references. Permuting input proposals does not change collation. Duplicate workers are not votes. A single agreed value stays `proposed_unverified`; any conflict remains unresolved. Cross-field constraints mark residual review work rather than silently rewriting values.

Byte matching and the merge operation share an explicit boundary. The complete quote “80” can support a proposal with value 900 as far as this byte checker can tell. There is no semantic validator, source reliability model, probabilistic confidence, calibrated abstention or scored argmax. Agreement on one source is not independent evidence.

The package is synchronous and deterministic except illustrative timing fields and request IDs. It has no network, model, plugin, code-execution or background-worker path. Direct library callers supply already-materialized objects and must apply workload bounds appropriate to their integration. The checked API and CLI add documented fixed bounds.

## Relationship to UnitBoost

UnitBoost describes a broader scored merge operator for compound language-model systems. This implementation explores source-bound receipts, deterministic collation and honest comparator evaluation. It does not reproduce UnitBoost's complete algorithm, residual-directed execution, model experiments or reported performance. The normalized-union tie is retained as a result, not presented as a new merge-method advantage.
