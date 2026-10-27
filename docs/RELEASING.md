# Release policy

Releases use semantic package versions and independently versioned saved-artifact formats. [Stability](STABILITY.md) defines the compatibility boundary; [the changelog](../CHANGELOG.md) records user-visible changes.

From a source checkout, run:

```sh
uv run --no-project --with-requirements requirements-dev.txt ruff check --no-cache .
uv run --no-project python scripts/verify_docs.py
PYTHONPATH=src uv run --no-project --with jsonschema==4.26.0 python -m unittest discover -s tests -v
uv run --no-project python scripts/verify_release.py
```

Lint uses the exact Ruff version in `requirements-dev.txt`; `pyproject.toml` requires that version. Build constraints are in `requirements-build.txt`. The optional validator is pinned in package metadata. CI runs the lint, documentation, source-test and installed-package gates. Passing checks are a release process requirement; no repository-host protection or security certification is implied.

The native gate retains per-command output, exit codes, a receipt and package SHA-256 hashes under `.release-scratch/`. It builds the wheel from the sdist, checks packaged examples and public docs, installs without runtime dependencies first, verifies missing schema support fails explicitly, then installs the extra and runs the full suite and command workflows.

Before distributing an artifact:

- Match package versions, source bytes and hashes to the intended source revision.
- Confirm all tests execute with no unexpected skips, and inspect every failure.
- Verify the README example and illustration links from the sdist.
- Check licence/NOTICE inclusion and third-party redistribution terms.
- Review exported files/history and package contents for private material.
- Retain the exact artifacts, checksums and check results with the release.

Git metadata, licence decisions, publication rights and remote release state require their own review. A package build does not authorize publication, establish hosted CI state or prove production behavior. Do not include local receipts, machine paths, handoffs, account data or raw datasets in distributions.

Keep versioned protocols, inputs and recorded negative results intact. Changes to active runner code must preserve documented comparisons or explicitly version a new experiment; illustrative CPU timings are not performance results.
