# Usage

Version 1.1.0 supports the interfaces and artifact formats in [the stability policy](STABILITY.md).
Use `unitmerge --version` to identify the installed package.

## Three-way configuration reconciliation

`unitmerge reconcile BASE LEFT RIGHT --report REPORT` accepts three ordinary
UTF-8 JSON documents. BASE is the common ancestor. Equal values or changes on
only one side merge automatically. Object keys recurse, including independent
additions beneath a newly added object. A deletion against an unchanged value
deletes the key; a deletion against a changed value conflicts at that key.
Object deletion versus an edited child conflicts at the parent. Arrays are
atomic, including additions to different array positions. Replacing a scalar
with two differing objects conflicts at the replacement path. Root scalars,
arrays and null are accepted. Numeric spellings parsed as integer versus float
(such as `1` and `1.0`) remain distinct, as do booleans and numbers. Object key
order does not affect value identity. Comments and JSONC are unsupported.

Decimal tokens (including exponent notation) must preserve their decimal value
through finite Python float parsing and normal JSON serialization. For example,
`0.1`, `1.25`, `1.2500` and `125e-2` are accepted. Values that round to another
decimal, such as `9007199254740993.0`, or underflow to zero, such as `1e-400`,
raise `ValueError` before review or output creation. Exact integer tokens such
as `9007199254740993` retain Python integer precision. Decimal spelling is
normalized in generated JSON; signed float zero is preserved.

Reports contain `inputs` with exact byte counts and SHA-256 hashes, an
`automatic` slot, `conflicts` and `report_sha256`. A slot with `present: false`
means missing, while `present: true, value: null` means JSON null. Conflicted
paths are omitted from `automatic`; that object is an incomplete review aid,
never a materialized output. Root conflicts have an absent automatic slot.
Conflict paths are JSON Pointers: `~` becomes `~0`, `/` becomes `~1`, the empty
string names the root, and `/` names a member whose key is the empty string.

`unitmerge resolve REPORT --base BASE --left LEFT --right RIGHT --decisions
DECISIONS --output MERGED` recomputes the report from the three original byte
strings. Any report change or input byte change fails. DECISIONS must contain
exactly `report_sha256` and `decisions`, a list of objects with exactly `path`
and `take`. Every conflict must occur exactly once, with `take` equal to
`base`, `left` or `right`. Unknown, duplicated and unresolved paths fail.
Conflict-free input requires an empty list. To use a different custom value,
edit an input and generate a new review.

The command creates MERGED and `MERGED.receipt.json` exclusively. If either
already exists, including a symlink, neither is overwritten. Reports, templates,
merged JSON and receipts are created with mode 0600 on POSIX, subject to a more
restrictive umask. This does not establish Windows ACLs or directory privacy.
Catchable write or close failures and interruptions attempt cleanup of every
created output while preserving the original failure. Cleanup is best effort:
an abrupt process or machine failure can leave an incomplete pair. Concurrent
path replacement or a filesystem denial can also prevent cleanup.
Check both files before using them or retrying. CLI errors, including bad command
syntax, return exit 2 with a private JSON error and request ID. Successful
report creation returns 0 even when conflicts remain; resolution returns 0
only after all choices have been validated and both files written.

Each configuration is at most 1 MiB, 64 nested levels and 10,000 JSON nodes
(including objects, arrays and their values). Generated JSON Pointers are at
most 4,096 UTF-8 bytes and canonical review content is at most 8 MiB. CLI review
and decision files are at most 16 MiB. Duplicate keys, nonfinite numbers
(including overflow such as `1e999`), invalid UTF-8 and unpaired surrogates
fail. These fixed bounds also apply to configuration bytes passed to the API.

```python
from pathlib import Path
from unitmerge.reconcile import reconcile, resolve

inputs = tuple(Path(f"examples/config-{side}.json").read_bytes()
               for side in ("base", "left", "right"))
report = reconcile(*inputs)
decisions = {
    "report_sha256": report["report_sha256"],
    "decisions": [{"path": "/logging/level", "take": "right"}],
}
result = resolve(report, decisions, *inputs)
merged, receipt = result["merged"], result["receipt"]
assert merged["service"]["port"] == 8080
```

The API returns detached JSON-compatible data and never writes files. Invalid
configuration, schema references or review decisions raise `ValueError`. Receipts bind the input
hashes, review hash, sorted decisions and canonical merged content hash. The
CLI adds a hash of the exact formatted output bytes. Canonical content uses
sorted keys, compact separators and literal UTF-8. Hashes are integrity
comparisons within caller-supplied data, not signatures or authenticated
history. Reports may contain sensitive values; preserve their privacy.
Without the optional schema, no schema validity is established. Neither mode
establishes semantic correctness or runtime service behavior. Examples are
authored software fixtures, not participant evidence.
The wheel also ships the fixtures under its installation prefix at
`share/unitmerge/examples/`; the source distribution keeps `examples/`.

## Review tools and output verification

`unitmerge review REPORT` validates the report's own format and digest, then
prints every conflict pointer and its base/left/right alternatives. `MISSING`
means absence; `null` means a present JSON null. Root is labeled `(root)`.
Strings and paths are JSON-escaped, including terminal controls. This is plain
text, with no HTML or shell execution. Configuration disclosure on stdout is
deliberate. It writes no files or decisions. It checks internal integrity only;
`resolve` still recomputes from the original inputs.

`unitmerge decisions-template REPORT --output DECISIONS` creates a new file
with the bound `report_sha256` and every conflict exactly once. Every choice
starts as `"UNRESOLVED"`. Edit `take` to `base`, `left` or `right`. The untouched
template fails whenever conflicts exist; a conflict-free template is complete.
Root, empty, slash/tilde and Unicode pointers are preserved exactly. Changing
inputs, policy or schema requires a new report and new choices.

`unitmerge verify-output MERGED --receipt RECEIPT` is read-only and validates
the resolution receipt's strict own-format shape before comparing the exact
output byte hash and canonical content hash. `MATCH` returns exit 0.
`BYTES_DIFFER` means content matches but byte representation changed;
`CONTENT_DIFFER` means the canonical content changed. Both return exit 1.
Malformed JSON/receipts return exit 2 privately. Output is at most 16 MiB,
64 levels and 30,000 nodes, allowing a union larger than any one input.
Receipt files retain the 16 MiB CLI bound. No file is rewritten. This does not
revalidate a schema or prove the decision history: a replaced consistent pair
can pass and is explicitly reported as unauthenticated.

Python equivalents are `decisions_template(report)`, `render_review(report)`
and `verify_output(output_bytes, receipt)` in `unitmerge.reconcile`. API-created
receipts need an `output_bytes_sha256` field added from the exact output bytes
before verification, as the API itself does not format or write output.

## Read-only resolution preview

`unitmerge preview REPORT --base BASE --left LEFT --right RIGHT --decisions
DECISIONS` rechecks the report against the original bytes and options without
creating merged JSON, receipts or other files. Supply the same `--schema` and
`--array-policy` used for reconciliation.

Missing choices and literal `UNRESOLVED` choices produce `NEEDS_DECISIONS`
with exit 1 and sorted `pending_paths`. Unknown or duplicate paths, invalid
choices, stale reports and unavailable schema support return exit 2 with empty
stdout and the private `INVALID_INPUT` stderr record. The resolver continues
to refuse missing or unresolved choices.

Complete choices produce `SCHEMA_REJECTED` with exit 1 if the candidate fails
the supplied schema. `schema_issues` contains at most 16 JSON Pointer paths and
schema keywords, without instance values or validator messages.
`schema_issues_truncated` is true only when further diagnostics exist. Pending
choices leave `schema_status` as `NOT_CHECKED`; schema-free complete choices use
`NOT_REQUESTED`. Local schemas remain trusted for computational cost.

`READY` returns exit 0 only after authoritative resolution succeeds. It includes
the resolver's `merged_content_sha256`, with `schema_status` of `PASS` when a
schema was supplied. Other statuses have a null merged hash. Every result uses
`unitmerge.preview.v1` and `semantic_correctness_established: false`. Paths and
schema keywords may disclose structure; keep diagnostics private.

The Python equivalent is `unitmerge.preflight.preview(report, decisions, base,
left, right, *, array_policy=None, schema=None)`. It returns the same detached
result without file I/O or caller-data mutation. Invalid input raises
`ValueError`. A later `resolve` call still rechecks its supplied bytes and options.

## Optional local JSON Schema

```sh
uv pip install '.[schema]'
.venv/bin/unitmerge reconcile base.json left.json right.json --schema service-schema.json --report review.json
.venv/bin/unitmerge decisions-template review.json --output decisions.json
# Review values and edit the unresolved choices, then:
.venv/bin/unitmerge resolve review.json --base base.json --left left.json --right right.json --schema service-schema.json --decisions decisions.json --output merged.json
```

The optional extra pins `jsonschema==4.26.0`. A schema is bounded like a
configuration (1 MiB, 64 levels, 10,000 nodes). Boolean schemas are supported.
Draft 2020-12 is used whether `$schema` is omitted or set to
`https://json-schema.org/draft/2020-12/schema`. Only fragment `$ref` and
`$dynamicRef` values are allowed. `$id`, external references (including local
files), and other `$schema` dialects at schema locations are refused.
The scan traverses actual subschemas and explicitly referenced targets, not
ordinary literal or annotation data. An empty, non-retrieving
registry prevents fallback fetching. Invalid schemas fail during review;
invalid candidates or unresolvable references fail before output creation.
Resolution also checks that every referenced target is itself a valid Draft
2020-12 schema, including references into annotations. Malformed targets fail
with the same private JSON error, without creating output or a receipt. Literal
objects inside `const` or `enum` remain data rather than reference instructions.
The caller should trust its local schema's computational cost: bounds do not
isolate expensive regular expressions or recursive schema evaluation.
`format` is informational, with no optional format checker installed.

Supply the same exact schema bytes to both commands. The schema SHA-256 is
bound into `unitmerge.reconcile.v2` and `unitmerge.resolution.v2` identities.
Missing schema support refuses the operation; it never silently omits checks.
Schema-free commands keep their existing behavior and v1 formats. Passing
`schema=bytes` to `reconcile` and `resolve` enables the same API contract.

## Optional keyed arrays

`--array-policy POLICY` reads a JSON object mapping literal JSON Pointer paths
to an entry's identity field, for example `{"/routes":"id", "/zones":"name"}`.
The same policy is required at review and resolution, and its canonical mapping
is included in the v2 review hash and receipt. JSON whitespace/key order in the
policy file is immaterial. `array_policy={...}` enables it through the API.

Policies have at most 64 paths. Paths use normal pointer escaping, traverse
object members only, cannot overlap, and must name an array in at least one
input. An absent target is allowed on other sides; present non-array targets
or non-object ancestors fail. Root `""` is allowed. Identity field names and
identity values must be nonempty strings of at most 256 UTF-8 bytes. Entries
must be objects with unique identities within each input, even if unchanged.
Missing, duplicate, numeric, null or empty identities fail. No identity is
inferred. Policy paths under arrays, nested keyed arrays and wildcards are
unsupported; unspecified arrays remain atomic.

Each identity's entire object is one merge unit. Independent IDs combine.
Identical changes combine, one changed side wins against an unchanged side,
and differing simultaneous changes conflict even if they changed different
fields. Deletion against an unchanged entry deletes it; deletion versus edit
conflicts. Identity changes are deletion plus addition. Whole-array deletion
versus an edited array still conflicts at the array's path. Keyed conflict
pointers append an escaped identity token, so `/routes/a~1b` means ID `a/b`,
not a numeric position. Read the alternatives before choosing a whole entry.

Every keyed result sorts entries by identity using Unicode code-point order,
including unchanged arrays and reorder-only edits. Input order has no merge
authority under this opt-in policy. This fixed rule is unsuitable for ordered
routes or other order-sensitive data; keep those arrays atomic. An empty
policy opts into v2 identity but changes no merge units. All input bytes still
bind exactly. Review hashes are unsigned and establish no identity authenticity.

Files named exactly `reconcile`, `review`, `decisions-template`, `resolve` or
`verify-output` in the packet interface need a path prefix such as `./review`
to distinguish them from commands.

## Installed example

Run `unitmerge --demo` after installation. The same command is available as `python -m unitmerge.cli --demo`. The JSON includes matched, rejected, conflicting and semantically false proposals. All examples are authored synthetic fixtures.

## Input contract

A proposal file is an object with:

- `units`: a nonempty list of unique, nonempty string IDs.
- `sources`: an object mapping source IDs to objects with boolean `current` flags.
- `proposals`: a list of objects with declared `unit_id`, declared `source_ref`, nonempty `worker_id` and finite JSON `value`. Null is valid.
- Optional `constraints`: objects with exactly `left`, `op`, `right`. Both endpoints are declared unit IDs; the operator is `<=`, `>=` or `==`. Ordered values must be numbers, not booleans. Equality uses canonical JSON identity.

For byte checking, each proposal also contains `evidence` with exactly `sha256`, `start`, `end`, `quote`. Supply `--sources source-texts.json`, a JSON object mapping IDs to literal source text. The digest covers the complete UTF-8 source. Offsets are half-open byte offsets, never character offsets. A span cutting a Unicode code point fails.

A minimal packet for the source map `{"s":"maximum 80"}`:

```json
{
  "units": ["max"],
  "sources": {"s": {"current": true}},
  "proposals": [{
    "unit_id": "max", "source_ref": "s", "worker_id": "w1", "value": 80,
    "evidence": {"sha256": "REPLACE_WITH_SHA256_OF_UTF8_SOURCE", "start": 8, "end": 10, "quote": "80"}
  }]
}
```

The digest placeholder deliberately fails receipt validation. Compute it from the exact bytes you supply, or construct a packet with the Python example below. Source strings are never dereferenced as local paths or fetched as URLs.

## Python API

```python
import hashlib
from unitmerge.evidence import checked_merge

blob = "maximum 80".encode("utf-8")
packet = {
    "units": ["max"], "sources": {"s": {"current": True}},
    "proposals": [{
        "unit_id": "max", "source_ref": "s", "worker_id": "w1", "value": 80,
        "evidence": {"sha256": hashlib.sha256(blob).hexdigest(),
                     "start": 8, "end": 10, "quote": "80"}
    }]
}
result = checked_merge(packet, {"s": blob})
assert result["evidence_receipts"][0]["status"] == "MATCHED_BYTES"
assert result["units"]["max"]["status"] == "proposed_unverified"
```

`unitmerge.core.merge(packet)` performs structural collation without byte checking. `eligible_payload` returns the eligible packet and a receipt for every original proposal, allowing comparators to share exactly the same inputs. Neither call mutates caller data.

## Bounds and errors

Each CLI JSON file is at most 16 MiB, with at most 64 nested levels. Duplicate keys, nonfinite proposed values, malformed JSON, invalid UTF-8 and invalid schemas fail. Checked receipt input allows at most 10,000 proposals, 256 source blobs, 1 MiB per source and 8 MiB of total source bytes. The caller must bound direct use of the structural-only library API to its own workload.

CLI success is exit 0 and JSON on stdout. Input errors are exit 2, empty stdout and a JSON stderr record containing `INVALID_INPUT` and a random request ID. Diagnostics omit local paths and input contents. Run `--help` for command syntax.

If a file cannot be opened, the message asks you to check that each input file exists and is readable. Check both the proposal file and the optional `--sources` file; each must be a readable file, rather than a directory. JSON and schema errors instead ask for finite, unique-key UTF-8 JSON within the documented limits. Fix the local input and rerun the same command.

Receipt failures remain data, not process failures: `SOURCE_UNAVAILABLE`, `RECEIPT_MISSING`, `INVALID_RECEIPT`, `DIGEST_MISMATCH` or `SPAN_MISMATCH`. The corresponding proposal cannot enter checked collation. A byte-matched stale proposal is recorded but cannot override a current source.

## Interpreting output

`proposed_unverified` means one surviving distinct value, `conflict` means multiple distinct values and `unsupported` means none. Repeated workers reading one source do not become independent votes. Unresolved units and violated cross-field constraints appear in `residual`; no majority or model breaks a conflict. Unknown extra descriptive fields have no authority.
