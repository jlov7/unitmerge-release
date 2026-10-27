# Changes

## 1.1.0

- Add the read-only `preview` CLI and `unitmerge.preflight.preview` API to check bound choices before resolution.
- Report pending conflict paths or bounded schema paths and keywords without disclosing instance values or writing files. `READY` returns exit 0; `NEEDS_DECISIONS` and `SCHEMA_REJECTED` return exit 1. Invalid input, stale reviews and unavailable schema support return exit 2.
- Preserve existing report and resolution formats, explicit-choice requirements and the semantic-correctness boundary.

## 1.0.1

- Create CLI reports, templates, merged JSON and receipts privately from the first byte on POSIX, independent of a permissive caller umask.
- Preserve the primary write, close or interruption failure while attempting cleanup of every created output, including failed stream construction.
- Interpret reserved JSON Schema keywords only at schema locations and explicitly referenced targets. Literal instance and annotation data remain accepted; external resources remain refused.
- Document best-effort cleanup and permission limits without changing saved report or receipt formats.
- Pin CI to Ubuntu 24.04 and include the technical review in documentation and package checks.

## 1.0.0

- Define the supported CLI, Python API, report/receipt formats and 1.x compatibility policy.
- Normalize malformed schema-pointer traversal through scalar annotation values to the documented `ValueError` API refusal. The CLI continues to return private structured errors.
- Refuse nonregular local file inputs before reading, including empty FIFOs and symlinks to them, while preserving symlinks to regular files.
- Add `unitmerge --version` and installed dependency/documentation checks.
- Verify partial-output cleanup and retry behavior for an injected receipt-write failure.
- Add a supplied-fixture quickstart, an accessible workflow illustration and recovery guidance.
- Pin the lint gate and resolve diagnostics without disabling rules. Frozen JSON comparisons and the no-advantage result are unchanged.

## 0.3.3

Validate local reference targets, including transitive and dynamic references, before materializing output. Preserve valid annotation targets, anchors, recursive schemas and reference-looking literal data.

## 0.3.2

Refuse decimal JSON tokens whose value changes through finite float parsing and JSON serialization. Preserve ordinary decimal/exponent values, signed zero and exact integer tokens.
