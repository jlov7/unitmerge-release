"""Read local JSON and report byte receipts without executing or fetching content."""
from __future__ import annotations

import argparse
import json
import os
import secrets
import stat
import sys
from pathlib import Path

from . import __version__
from .core import MergeInputError, merge
from .evidence import checked_merge
from .reconcile import (
    ReviewMismatch,
    SchemaSupportMissing,
    decisions_template,
    reconcile,
    render_review,
    resolve,
    verify_output,
)

MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_DEPTH = 64


class PrivateParser(argparse.ArgumentParser):
    def error(self, _message):
        sys.stderr.write(json.dumps({'error': 'INVALID_INPUT',
                                     'request_id': secrets.token_hex(8),
                                     'message': 'Check command syntax with --help.'}) + '\n')
        raise SystemExit(2)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate object key')
        result[key] = value
    return result


def _constant(_value):
    raise ValueError('nonfinite JSON number')


def _read_file(path, limit):
    flags = os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0)
    descriptor = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError('input must be a regular file')
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            return stream.read(limit + 1)
    finally:
        os.close(descriptor)


def _read_json(path: Path, max_depth=MAX_DEPTH):
    raw = _read_file(path, MAX_INPUT_BYTES)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError('input exceeds byte limit')
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs, parse_constant=_constant)
    pending = [(value, 0)]
    while pending:
        node, depth = pending.pop()
        if depth > max_depth:
            raise ValueError('input nesting exceeds limit')
        if isinstance(node, (dict, list)):
            pending.extend((child, depth + 1) for child in
                           (node.values() if isinstance(node, dict) else node))
    return value


def _read_config(path, multiplier=1):
    from .reconcile import MAX_INPUT_BYTES as limit
    limit *= multiplier
    raw = _read_file(path, limit)
    if len(raw) > limit:
        raise ValueError('configuration exceeds byte limit')
    return raw


def _encode(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                       allow_nan=False) + '\n').encode('utf-8')


def _open_output(path):
    """Create a file exclusively, with private permissions from the first byte."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        return os.fdopen(descriptor, 'wb')
    except BaseException:
        # Stream construction may already have closed the descriptor.
        # Cleanup must neither replace the primary error nor skip unlink.
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _write_new(outputs):
    """Write an exclusive pair; best-effort cleanup is not crash atomicity."""
    opened = []
    try:
        for path, data in outputs:
            stream = _open_output(path)
            opened.append((path, stream))
        for (_, stream), (_, data) in zip(opened, outputs):
            if stream.write(data) != len(data):
                raise OSError('short output write')
            stream.close()
    except BaseException:
        # A close or unlink failure must not abandon later files or replace the
        # original error. Catchable cancellation follows the same cleanup path.
        for path, stream in opened:
            try:
                stream.close()
            except OSError:
                pass
            try:
                path.unlink()
            except OSError:
                pass
        raise


def _configuration_command(command):
    parser = PrivateParser(prog='unitmerge ' + command)
    if command == 'reconcile':
        for side in ('base', 'left', 'right'):
            parser.add_argument(side, type=Path)
        parser.add_argument('--report', required=True, type=Path)
    elif command == 'resolve':
        parser.add_argument('report', type=Path)
        for name in ('base', 'left', 'right', 'decisions', 'output'):
            parser.add_argument('--' + name, required=True, type=Path)
    elif command in ('review', 'decisions-template'):
        parser.add_argument('report', type=Path)
        if command == 'decisions-template':
            parser.add_argument('--output', required=True, type=Path)
    elif command == 'verify-output':
        parser.add_argument('output', type=Path)
        parser.add_argument('--receipt', required=True, type=Path)
    if command in ('reconcile', 'resolve'):
        parser.add_argument('--array-policy', type=Path, help='local pointer-to-identity-key JSON')
        parser.add_argument('--schema', type=Path, help='local Draft 2020-12 JSON Schema (extra)')
    args = parser.parse_args(sys.argv[2:])
    try:
        if command in ('review', 'decisions-template'):
            report = _read_json(args.report, MAX_DEPTH + 6)
            if command == 'review':
                sys.stdout.write(render_review(report))
                return 0
            _write_new([(args.output, _encode(decisions_template(report)))])
            summary = {'status': 'TEMPLATE_CREATED', 'report_sha256': report['report_sha256']}
        elif command == 'verify-output':
            summary = verify_output(_read_config(args.output, 16), _read_json(args.receipt))
            sys.stdout.write(json.dumps(summary, sort_keys=True) + '\n')
            return 0 if summary['status'] == 'MATCH' else 1
        else:
            inputs = tuple(_read_config(path) for path in (args.base, args.left, args.right))
            options = {'array_policy': _read_json(args.array_policy) if args.array_policy else None,
                       'schema': _read_config(args.schema) if args.schema else None}
        if command == 'reconcile':
            report = reconcile(*inputs, **options)
            _write_new([(args.report, _encode(report))])
            summary = {'status': 'REQUIRES_REVIEW' if report['conflicts'] else 'READY',
                       'conflicts': len(report['conflicts']),
                       'report_sha256': report['report_sha256']}
        elif command == 'resolve':
            report = _read_json(args.report, MAX_DEPTH + 6)
            decisions = _read_json(args.decisions)
            result = resolve(report, decisions, *inputs, **options)
            merged = _encode(result['merged'])
            from hashlib import sha256
            result['receipt']['output_bytes_sha256'] = sha256(merged).hexdigest()
            _write_new([(args.output, merged),
                        (Path(str(args.output) + '.receipt.json'), _encode(result['receipt']))])
            summary = {'status': 'MATERIALIZED', 'receipt': result['receipt']}
    except (OSError, ValueError, TypeError, RecursionError, UnicodeError) as exc:
        error = {'error': 'INVALID_INPUT', 'request_id': secrets.token_hex(8),
                 'message': 'Check finite unique-key UTF-8 JSON, review hashes, complete '
                            'decisions, readable inputs and unused output names.'}
        if isinstance(exc, SchemaSupportMissing):
            error['message'] = 'Install unitmerge[schema] before using --schema.'
        elif isinstance(exc, ReviewMismatch):
            error['message'] = ('Review no longer matches the inputs or options. Run reconcile '
                                'again, then review and regenerate decisions before resolving.')
        sys.stderr.write(json.dumps(error) + '\n')
        return 2
    sys.stdout.write(json.dumps(summary, sort_keys=True) + '\n')
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == 'preview':
        from .preflight import main as preview_main
        return preview_main(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] in ('reconcile', 'resolve', 'decisions-template',
                                          'review', 'verify-output'):
        return _configuration_command(sys.argv[1])
    parser = PrivateParser(description='Reconcile JSON or check source-byte proposals',
                           epilog='Configuration commands: reconcile, review, decisions-template, '
                                  'preview, resolve, verify-output (each accepts --help)')
    parser.add_argument('--version', action='version', version=f'unitmerge {__version__}')
    parser.add_argument('input', nargs='?', type=Path, help='local proposal JSON file')
    parser.add_argument('--sources', type=Path, help='JSON mapping source IDs to literal UTF-8 text')
    parser.add_argument('--demo', action='store_true', help='run four synthetic receipt cases')
    args = parser.parse_args()
    if (args.demo and (args.input or args.sources)) or (not args.demo and not args.input):
        parser.error('provide an input file or --demo')
    try:
        if args.demo:
            from .demo import run
            result = run()
        else:
            payload = _read_json(args.input)
            if args.sources:
                texts = _read_json(args.sources)
                if type(texts) is not dict or any(type(v) is not str for v in texts.values()):
                    raise MergeInputError('sources must map IDs to literal UTF-8 text')
                result = checked_merge(payload, {k: v.encode('utf-8') for k, v in texts.items()})
            else:
                result = merge(payload)
        encoded = json.dumps(result, indent=2, sort_keys=True, allow_nan=False)
    except (OSError, ValueError, TypeError, RecursionError, UnicodeError) as exc:
        error = {'error': 'INVALID_INPUT', 'request_id': secrets.token_hex(8),
                 'message': 'Use finite, unique-key UTF-8 JSON within the documented schema and limits.'}
        if isinstance(exc, OSError):
            error['message'] = 'Check that each input file exists and is readable.'
        sys.stderr.write(json.dumps(error) + '\n')
        return 2
    sys.stdout.write(encoded + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
