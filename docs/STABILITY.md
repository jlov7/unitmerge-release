# Stable contracts

Package version 1.0.0 begins the 1.x compatibility policy. Stability applies to the documented software interfaces, not to semantic correctness, human usefulness or research efficacy.

## Command line

The supported entry points are `unitmerge` and `python -m unitmerge.cli`. Top-level `--version` prints `unitmerge VERSION` and exits 0; help is plain text. The packet interface accepts a local JSON file, optional `--sources`, or `--demo`. Configuration commands are `reconcile`, `review`, `decisions-template`, `preview`, `resolve` and `verify-output`; their documented positional arguments and flags remain available throughout 1.x.

Successful machine-readable operations emit JSON on stdout. `review` intentionally emits escaped plain text containing configuration alternatives. Exit 0 means the command completed, including a report with conflicts. `verify-output` returns exit 1 for a valid comparison that differs. `preview` returns exit 0 for `READY` and exit 1 for `NEEDS_DECISIONS` or `SCHEMA_REJECTED`; it creates no files. Invalid input, unavailable schema support, unresolved choices passed to `resolve`, stale artifacts and ordinary I/O failures return exit 2, empty stdout and one JSON stderr record with `error: INVALID_INPUT`, a nonempty request ID and a privacy-preserving message. Message prose and request IDs are not stable machine interfaces. Use error/status fields and exit codes.

Configuration report statuses are `READY` and `REQUIRES_REVIEW`; creation commands return `TEMPLATE_CREATED` or `MATERIALIZED`. Verification returns `MATCH`, `BYTES_DIFFER` or `CONTENT_DIFFER`, plus `bytes_match`, `content_match` and `authenticated: false`. The packet workflow retains the documented unit statuses, receipt reasons, residual fields and unverified-truth boundary in [usage](USAGE.md).

Local file inputs must resolve to regular files. Symlinks to regular files retain the target's exact bytes; FIFOs, devices and other nonregular inputs are refused. On platforms with nonblocking file open, descriptor validation occurs before any read.

Every created output name must be unused. Existing files and symlinks are never overwritten. Reports, templates, merged JSON and receipts are created with mode 0600 on POSIX, subject to a more restrictive umask; Windows ACLs and directory privacy are not established. Catchable write or close failures and interruptions attempt cleanup of every created output, preserving the primary failure even when descriptor close or removal fails. Cleanup is best effort, not a two-file transaction: process/machine failure, concurrent path replacement or removal denial can leave files. Inspect the pair after such a failure.

## Python API

Supported functions:

| Module | Functions |
| --- | --- |
| `unitmerge.reconcile` | `reconcile`, `resolve`, `decisions_template`, `render_review`, `verify_output` |
| `unitmerge.preflight` | `preview` |
| `unitmerge.core` | `merge`, and its `MergeInputError` exception |
| `unitmerge.evidence` | `eligible_payload`, `checked_merge` |
| `unitmerge.baselines` | `normalized_union`, `single_worker` |

The documented argument names, keyword-only schema/policy options and return structures remain supported in 1.x. `unitmerge.__version__` is the installed package version. Underscore-prefixed helpers, demo internals and experiment runners are not supported API entry points.

Configuration documents and schemas are bounded UTF-8 `bytes`. Reports, decisions, receipts and policies use JSON-compatible built-in dictionaries/lists and their documented scalar types. Use reports produced by `reconcile`, and supply the original bytes to `resolve`. Configuration APIs reject invalid documented inputs with `ValueError`; `ReviewMismatch` and `SchemaSupportMissing` are more specific subclasses. Structural/checked proposal validation uses `MergeInputError`, also a `ValueError`. The baseline helpers require the structurally validated eligible payload used by the comparison. No resource-isolation promise applies to arbitrary Python objects or an unbounded direct structural API workload.

The APIs do not write files or mutate caller data. API resolution receipts contain the canonical content hash. Add `output_bytes_sha256` from the exact serialized output before calling `verify_output`. Library error text and incidental object representation are not stable interfaces.

## Saved artifacts

Package versions and artifact format identifiers are separate:

| Artifact | Identifier / shape |
| --- | --- |
| Schema-free configuration report | `unitmerge.reconcile.v1` |
| Report with an explicit schema or array policy | `unitmerge.reconcile.v2` |
| Corresponding resolution receipt | `unitmerge.resolution.v1` or `unitmerge.resolution.v2` |
| Read-only preview | `unitmerge.preview.v1` |
| Choices | Exactly `report_sha256` and a `decisions` list of `path`/`take` objects |

1.0.0 preserves the existing v1/v2 formats. V2 binds the canonical array policy and the exact schema-byte hash; even an explicit empty policy opts into v2. Unknown format versions, fields or choices are refused rather than silently interpreted. The output JSON itself has no UnitMerge wrapper.

JSON Pointer escaping, missing-versus-null slots, object recursion, atomic arrays, whole-entry keyed choices and ID sorting retain the behavior in [usage](USAGE.md). Input spellings that differ in integer/float identity remain distinct. Decimal values must survive the documented finite float round trip.

Hashes use SHA-256. Canonical JSON sorts keys, uses compact separators, literal UTF-8 and finite numbers. Input and schema identity use exact original bytes. The report hash excludes only its own `report_sha256` field. Saved artifacts are unsigned and establish no reviewer/source authenticity.

Within 1.x, a saved report can be resumed when it reproduces under the documented contract from the same input bytes/options and every conflict has an explicit bound choice. If a correctness repair makes an old invalid artifact fail validation, generate and review a new report. Do not edit old artifacts or bypass hash checks to force acceptance.

## Change policy

Patch releases repair behavior that violates the contract, improve diagnostics and update tooling. Correctness/security repairs may refuse malformed inputs previously accepted by mistake; those changes must be described in the changelog. Minor releases may add opt-in capabilities while retaining existing command/function behavior. Removing or incompatibly changing a supported interface requires a major version.

An incompatible artifact interpretation requires a new format identifier and documented migration. Existing reports/receipts are not silently rewritten. Limits and supported Python versions are documented release constraints; changes are called out in release notes. CI covers Python 3.11, 3.12 and 3.13, and release evidence identifies the platforms actually exercised. Compatibility policy is a maintenance commitment, not proof that every platform or downstream service has been validated.
