"""Read-only resolution preflight; never select an alternative or create an output.

Paths and schema keywords are disclosed, but instance values and validator error
messages are not. The existing resolver remains authoritative for READY results.
"""
from __future__ import annotations

import json
import secrets
import sys
from pathlib import Path

from .reconcile import (
    ReviewMismatch,
    SchemaSupportMissing,
    _canonical,
    _decode,
    _normalize,
    _schema,
    _walk,
    decisions_template,
    reconcile,
    resolve,
)

ISSUE_LIMIT = 16


def preview(report: dict, decisions: dict, base: bytes, left: bytes, right: bytes,
            *, array_policy=None, schema=None) -> dict:
    """Classify current choices without writing or relaxing the resolution contract.

    Missing choices and literal UNRESOLVED are allowed only in this diagnostic.
    Unknown/duplicate paths, invalid decisions and stale review bytes are errors.
    Schema diagnostics are capped; local schemas remain trusted for compute cost.
    """
    template = decisions_template(report)  # Validate the report before inspecting it.
    raw = (base, left, right)
    expected = reconcile(*raw, array_policy=array_policy, schema=schema)
    if _canonical(report) != _canonical(expected):
        raise ReviewMismatch('stale or modified review')
    if (type(decisions) is not dict or set(decisions) != {'report_sha256', 'decisions'} or
            decisions['report_sha256'] != expected['report_sha256'] or
            type(decisions['decisions']) is not list or
            len(decisions['decisions']) > len(template['decisions'])):
        raise ValueError('invalid decisions')
    paths = {item['path'] for item in template['decisions']}
    chosen, seen = {}, set()
    for item in decisions['decisions']:
        if (type(item) is not dict or set(item) != {'path', 'take'} or
                type(item['path']) is not str or item['path'] not in paths or
                item['path'] in seen or type(item['take']) is not str or
                item['take'] not in ('base', 'left', 'right', 'UNRESOLVED')):
            raise ValueError('invalid conflict decision')
        seen.add(item['path'])
        if item['take'] != 'UNRESOLVED':
            chosen[item['path']] = item['take']
    result = {'format': 'unitmerge.preview.v1', 'status': 'NEEDS_DECISIONS',
              'report_sha256': expected['report_sha256'],
              'resolved_count': len(chosen), 'pending_paths': sorted(paths - chosen.keys()),
              'schema_status': 'NOT_CHECKED', 'schema_issues': [],
              'schema_issues_truncated': False, 'merged_content_sha256': None,
              'semantic_correctness_established': False}
    if result['pending_paths']:
        return result
    if schema is not None:
        from referencing.exceptions import Unresolvable
        policy = {} if array_policy is None else array_policy
        values = tuple(_decode(value) for value in raw)
        if policy:
            values = tuple(_normalize(value, policy) for value in values)
        candidate = _walk(*values, '', [], chosen, policy)
        try:
            validator = _schema(schema, check_references=True)
            for error in validator.iter_errors(candidate):
                if len(result['schema_issues']) == ISSUE_LIMIT:
                    result['schema_issues_truncated'] = True
                    break
                path = ''.join('/' + str(part).replace('~', '~0').replace('/', '~1')
                               for part in error.absolute_path)
                result['schema_issues'].append({'path': path, 'keyword': str(error.validator)})
        except (Unresolvable, RecursionError) as error:
            raise ValueError('invalid schema reference') from error
        result['schema_issues'].sort(key=lambda item: (item['path'], item['keyword']))
        if result['schema_issues']:
            result.update(status='SCHEMA_REJECTED', schema_status='FAIL')
            return result
    # Authoritative full resolution rechecks every field and option. No file I/O.
    resolved = resolve(report, decisions, *raw, array_policy=array_policy, schema=schema)
    result.update(status='READY', schema_status='PASS' if schema is not None else 'NOT_REQUESTED',
                  merged_content_sha256=resolved['receipt']['merged_content_sha256'])
    return result


def main(argv=None):
    from .cli import MAX_DEPTH, PrivateParser, _read_config, _read_json
    parser = PrivateParser(
        prog='unitmerge preview', description=__doc__,
        epilog='Exit 0: READY. Exit 1: NEEDS_DECISIONS or SCHEMA_REJECTED. '
               'Exit 2: invalid input, stale review or unavailable schema support.')
    parser.add_argument('report', type=Path)
    for name in ('base', 'left', 'right', 'decisions'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--schema', type=Path)
    parser.add_argument('--array-policy', type=Path)
    args = parser.parse_args(argv)
    try:
        raw = tuple(_read_config(path) for path in (args.base, args.left, args.right))
        result = preview(_read_json(args.report, MAX_DEPTH + 6), _read_json(args.decisions),
                         *raw, schema=_read_config(args.schema) if args.schema else None,
                         array_policy=_read_json(args.array_policy) if args.array_policy else None)
    except (OSError, ValueError, TypeError, RecursionError, UnicodeError) as error:
        message = 'Check the review, input files, choices, options and documented bounds.'
        if isinstance(error, ReviewMismatch):
            message = 'The review is stale. Reconcile current files/options and review choices again.'
        elif isinstance(error, SchemaSupportMissing):
            message = 'Install unitmerge[schema] before using --schema.'
        sys.stderr.write(json.dumps({'error': 'INVALID_INPUT', 'request_id': secrets.token_hex(8),
                                     'message': message}) + '\n')
        return 2
    sys.stdout.write(json.dumps(result, sort_keys=True, allow_nan=False) + '\n')
    return 0 if result['status'] == 'READY' else 1


if __name__ == '__main__':
    raise SystemExit(main())
