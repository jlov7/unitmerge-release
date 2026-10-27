# Contributing

Start with the README's installed demo and the full test suite. A bug report should include a minimal authored or redistributable input, the command, expected behavior, actual behavior and version. Remove source text, private paths and identifiers you cannot share.

For installation/help, start with [the README](README.md) and include the output of `unitmerge --version` in a minimal synthetic issue. Support has no response-time guarantee. For release compatibility, see [stability](docs/STABILITY.md) and [release policy](docs/RELEASING.md).

For changes, reproduce the failure before the fix, add a regression test and run `PYTHONPATH=src uv run --no-project --with jsonschema==4.26.0 python -m unittest discover -s tests -v` and `uv run --no-project python scripts/verify_release.py`. The schema tests must execute, not skip. Preserve frozen experiment inputs, protocols, negative outcomes and denominators. Add a new versioned protocol for a new hypothesis rather than editing historical results.

Keep runtime dependencies minimal. Proposals must not fetch sources, execute instructions or promote agreement into truth. Describe the claim boundary and simplest comparator with any evaluation change. Never add credentials, confidential data, unlicensed corpora or generated private logs to a contribution.

Run `uv run --no-project --with-requirements requirements-dev.txt ruff check --no-cache .` and `uv run --no-project python scripts/verify_docs.py` as well. Do not disable lint rules to hide a diagnostic. Public documentation and illustrations must ship in the source distribution.
