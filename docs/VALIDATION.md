# Validation

The source and installed-package checks exercise local JSON reconciliation. Run
the commands in [README](../README.md#development-and-release) and the
[release procedure](RELEASING.md) against the exact revision being evaluated.

| Contract | Discriminating checks | Limit |
| --- | --- | --- |
| Conflicts need explicit, byte-bound decisions | [Reconciliation](../tests/test_reconcile.py), [review tools](../tests/test_review_tools.py) | A choice does not establish application correctness |
| Preview uses the authoritative resolver and creates no files | [Preview statuses and bounds](../tests/test_resolution_preview.py) | Schema paths can disclose structure |
| Schema instructions are interpreted only at schema locations | [Schema-location cases](../tests/test_schema_locations.py) | Only the supported local schema profile is accepted |
| Outputs start with private POSIX permissions | [Output integrity](../tests/test_output_integrity.py) | Parent-directory trust and Windows ACLs remain separate |
| Catchable cleanup failures preserve the triggering error | [Descriptor cleanup](../tests/test_descriptor_cleanup.py) | Cleanup is best effort, not crash-atomic multi-file output |

The package gate builds an sdist and its wheel, checks distribution membership,
installs outside the source tree, and exercises installed tests, examples and
refusal controls. [Evaluation](EVALUATION.md) preserves the tied and negative
research comparisons. These checks do not establish production safety, semantic
truth, human productivity or the original paper's results.
