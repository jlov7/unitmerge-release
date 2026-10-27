"""Hand-checked configuration merge cases and review custody boundaries."""
import copy
import itertools
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_cli

from unitmerge import cli
from unitmerge.reconcile import reconcile, resolve


def blob(value):
    return json.dumps(value, ensure_ascii=False).encode('utf-8')


class ReconciliationTests(unittest.TestCase):
    def review(self, base, left, right):
        inputs = tuple(map(blob, (base, left, right)))
        return inputs, reconcile(*inputs)

    def finish(self, inputs, report, choices=()):
        decisions = {'report_sha256': report['report_sha256'], 'decisions': list(choices)}
        return resolve(report, decisions, *inputs)

    def test_hand_checked_disjoint_matrix(self):
        cases = [
            ({}, {'a': 1}, {'b': 2}, {'a': 1, 'b': 2}),
            ({'a': 1, 'b': 2}, {'b': 2}, {'a': 1, 'b': 3}, {'b': 3}),
            ({'a': 1}, {'a': None}, {'a': 1}, {'a': None}),
            ({'a': None}, {}, {'a': None}, {}),
            ({'a': 1}, {}, {}, {}),
            ({'a': {}}, {'a': {'x': 1}}, {'a': {'y': 2}}, {'a': {'x': 1, 'y': 2}}),
            ({}, {'a': {'x': 1}}, {'a': {'y': 2}}, {'a': {'x': 1, 'y': 2}}),
            ([1], [1, 2], [1], [1, 2]),
            (None, {'a': 1}, None, {'a': 1}),
        ]
        for base, left, right, expected in cases:
            with self.subTest(base=base, left=left, right=right):
                inputs, report = self.review(base, left, right)
                self.assertEqual(report['conflicts'], [])
                result = self.finish(inputs, report)
                self.assertEqual(result['merged'], expected)
                self.assertFalse(result['receipt']['semantic_correctness_established'])

    def test_conflict_matrix_and_explicit_deletion_null(self):
        for base, left, right, path in [
            ({'a': 0}, {'a': 1}, {'a': 2}, '/a'),
            ({'a': 0}, {}, {'a': None}, '/a'),
            ({'a': {'x': 0}}, {}, {'a': {'x': 1}}, '/a'),
            ({'a': [0]}, {'a': [0, 1]}, {'a': [0, 2]}, '/a'),
            ({}, {'a': True}, {'a': 1}, '/a'),
            (0, 1, 2, ''),
            ({'~/': {'': 0}}, {'~/': {'': 1}}, {'~/': {'': 2}}, '/~0~1/'),
        ]:
            with self.subTest(path=path, base=base):
                inputs, report = self.review(base, left, right)
                self.assertEqual([c['path'] for c in report['conflicts']], [path])
                with self.assertRaises(ValueError):
                    self.finish(inputs, report)
                for side, expected in [('base', base), ('left', left), ('right', right)]:
                    result = self.finish(inputs, report, [{'path': path, 'take': side}])
                    self.assertEqual(result['merged'], expected)

    def test_deterministic_order_no_mutation_and_receipt(self):
        inputs, report = self.review({'z': 0, 'a': 0}, {'z': 1, 'a': 1}, {'z': 2, 'a': 2})
        saved = copy.deepcopy(report)
        self.assertEqual([c['path'] for c in report['conflicts']], ['/a', '/z'])
        choices = [{'path': '/z', 'take': 'right'}, {'path': '/a', 'take': 'left'}]
        a = self.finish(inputs, report, choices)
        b = self.finish(inputs, report, reversed(choices))
        self.assertEqual(a, b)
        self.assertEqual(a['merged'], {'a': 1, 'z': 2})
        self.assertEqual(report, saved)
        self.assertEqual(a['receipt']['report_sha256'], report['report_sha256'])
        self.assertEqual(reconcile(*inputs), report)

    def test_independent_one_field_reference_matrix(self):
        # Exhaustive scalar/atomic-array reference: the sole changed side wins;
        # two different changed sides require an explicit decision.
        missing = object()
        values = [missing, None, False, 0, 1, 'x', [], [1]]
        def identity(value):
            return 'missing' if value is missing else json.dumps(value)
        def document(value):
            return {} if value is missing else {'x': value}
        for base, left, right in itertools.product(values, repeat=3):
            b, l, r = map(identity, (base, left, right))
            conflict = l != r and l != b and r != b
            expected = right if conflict or l == b else left
            inputs, report = self.review(*map(document, (base, left, right)))
            self.assertEqual(len(report['conflicts']), int(conflict))
            decisions = [{'path': '/x', 'take': 'right'}] if conflict else []
            self.assertEqual(self.finish(inputs, report, decisions)['merged'], document(expected))

    def test_reject_stale_bytes_tampered_artifact_and_invalid_decisions(self):
        inputs, report = self.review({'a': 0}, {'a': 1}, {'a': 2})
        good = {'report_sha256': report['report_sha256'],
                'decisions': [{'path': '/a', 'take': 'right'}]}
        for invalid in [
            {**good, 'extra': 1}, {**good, 'report_sha256': '0' * 64},
            {**good, 'decisions': []},
            {**good, 'decisions': good['decisions'] * 2},
            {**good, 'decisions': [{'path': '/nope', 'take': 'left'}]},
            {**good, 'decisions': [{'path': '/a', 'take': 'unknown'}]},
            {**good, 'decisions': [{'path': '/a', 'take': 'left', 'value': 99}]},
        ]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                resolve(report, invalid, *inputs)
        modified = copy.deepcopy(report)
        modified['conflicts'][0]['left']['value'] = 100
        with self.assertRaises(ValueError):
            resolve(modified, good, *inputs)
        with self.assertRaises(ValueError):
            resolve(report, good, inputs[0] + b' ', *inputs[1:])

    def test_bounded_strict_json(self):
        for raw in [b'{"a":1,"a":2}', b'NaN', b'1e999', b'"\\ud800"', b'\xff',
                    b'[' * 66 + b'0' + b']' * 66, b'{invalid']:
            with self.subTest(raw=raw[:30]), self.assertRaises(ValueError):
                reconcile(raw, b'{}', b'{}')
        with patch('unitmerge.reconcile.MAX_INPUT_BYTES', 32), self.assertRaises(ValueError):
            reconcile(b' ' * 33, b'{}', b'{}')
        with patch('unitmerge.reconcile.MAX_NODES', 4), self.assertRaises(ValueError):
            reconcile(b'{"a":1,"b":2,"c":3,"d":4}', b'{}', b'{}')
        with patch('unitmerge.reconcile.MAX_POINTER_BYTES', 2), self.assertRaises(ValueError):
            self.review({'long': 0}, {'long': 1}, {'long': 2})
        with patch('unitmerge.reconcile.MAX_REVIEW_BYTES', 2), self.assertRaises(ValueError):
            self.review({}, {}, {})

    def test_decimal_rounding_and_underflow_are_refused(self):
        for token in (b'9007199254740993.0', b'-9007199254740993.0',
                      b'1e-400', b'-1e-400', b'1.0000000000000001',
                      b'1e-99999999999999999999999999'):
            for side in range(3):
                inputs = [b'{"n":0}', b'{"n":9007199254740992.0}', b'{"n":0}']
                inputs[side] = b'{"n":' + token + b'}'
                with self.subTest(token=token, side=side), self.assertRaises(ValueError) as error:
                    reconcile(*inputs)
                self.assertNotIn(token.decode(), str(error.exception))

    def test_decimal_controls_preserve_values_and_numeric_distinctions(self):
        raw = (b'[0.1,1.25,1.2500,125e-2,1E+2,-1.25,0e0,-0e0,0.0,-0.0,'
               b'9007199254740993,-9007199254740993,9007199254740992.0,1e-300,5e-324]')
        report = reconcile(raw, raw, raw)
        result = self.finish((raw, raw, raw), report)
        self.assertEqual(json.dumps(result['merged'], separators=(',', ':')),
                         '[0.1,1.25,1.25,1.25,100.0,-1.25,0.0,-0.0,0.0,-0.0,'
                         '9007199254740993,-9007199254740993,9007199254740992.0,1e-300,5e-324]')
        for base, left, right in ((b'0', b'1', b'1.0'), (b'1.0', b'0.0', b'-0.0')):
            with self.subTest(left=left, right=right):
                inputs = (base, left, right)
                report = reconcile(*inputs)
                self.assertEqual([c['path'] for c in report['conflicts']], [''])
                result = self.finish(inputs, report, [{'path': '', 'take': 'right'}])
                self.assertEqual(json.dumps(result['merged']).encode(), right)


class ReconciliationCommandTests(unittest.TestCase):
    invoke = test_cli.CommandTests.invoke

    def test_cli_lossy_decimals_create_no_review_or_resolution(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            paths = [root / f'{side}.json' for side in ('base', 'left', 'right')]
            for path in paths:
                path.write_bytes(b'{"n":0}')
            report, decisions = [root / f'{s}.json' for s in ('review', 'decisions')]
            self.assertEqual(self.invoke(['reconcile', *paths, '--report', report])[0], 0)
            decisions.write_bytes(blob({'report_sha256': json.loads(report.read_text())['report_sha256'],
                                        'decisions': []}))
            for index, token in enumerate((b'9007199254740993.0', b'1e-400', b'-1e-400')):
                refused_review = root / f'refused-review-{index}.json'
                output = root / f'merged-{index}.json'
                review_args = ['reconcile', *paths, '--report', refused_review]
                resolve_args = ['resolve', report, '--base', paths[0], '--left', paths[1],
                                '--right', paths[2], '--decisions', decisions, '--output', output]
                paths[2].write_bytes(b'{"n":' + token + b'}')
                for args in (review_args, resolve_args):
                    with self.subTest(token=token, command=args[0]):
                        code, out, err = self.invoke(args)
                        self.assertEqual((code, out), (2, ''))
                        self.assertEqual(json.loads(err)['error'], 'INVALID_INPUT')
                        self.assertIn('request_id', json.loads(err))
                        self.assertNotIn(token.decode(), err)
                        self.assertNotIn(name, err)
                        self.assertFalse(refused_review.exists())
                        self.assertFalse(output.exists())
                        self.assertFalse(Path(str(output) + '.receipt.json').exists())

    def test_cli_benign_numeric_review_and_resolution(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            path, report, decisions, output = [root / f'{s}.json' for s in
                                               ('input', 'review', 'decisions', 'merged')]
            path.write_bytes(b'{"n":[0.1,1.25,125e-2,1E+2,-0.0,9007199254740993]}')
            self.assertEqual(self.invoke(['reconcile', path, path, path, '--report', report])[0], 0)
            decisions.write_bytes(blob({'report_sha256': json.loads(report.read_text())['report_sha256'],
                                        'decisions': []}))
            args = ['resolve', report, '--base', path, '--left', path, '--right', path,
                    '--decisions', decisions, '--output', output]
            self.assertEqual(self.invoke(args)[0], 0)
            self.assertEqual(json.dumps(json.loads(output.read_bytes()), separators=(',', ':')),
                             '{"n":[0.1,1.25,1.25,100.0,-0.0,9007199254740993]}')

    def test_cli_review_then_resolve_and_existing_outputs(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            paths = [root / (side + '.json') for side in ('base', 'left', 'right')]
            for path, value in zip(paths, ({'x': 0, 'a': 0}, {'x': 1, 'a': 0},
                                         {'x': 2, 'a': 1})):
                path.write_bytes(blob(value))
            report_path, decisions, output = [root / f'{s}.json' for s in
                                              ('review', 'decisions', 'merged')]
            code, out, err = self.invoke(['reconcile', *paths, '--report', report_path])
            self.assertEqual((code, err), (0, ''))
            self.assertEqual(json.loads(out)['status'], 'REQUIRES_REVIEW')
            report = json.loads(report_path.read_text())
            decisions.write_bytes(blob({'report_sha256': report['report_sha256'],
                                        'decisions': [{'path': '/x', 'take': 'right'}]}))
            args = ['resolve', report_path, '--base', paths[0], '--left', paths[1],
                    '--right', paths[2], '--decisions', decisions, '--output', output]
            self.assertEqual(self.invoke(args)[0], 0)
            self.assertEqual(json.loads(output.read_text()), {'x': 2, 'a': 1})
            self.assertTrue(Path(str(output) + '.receipt.json').is_file())
            saved = output.read_bytes()
            self.assertEqual(self.invoke(args)[0], 2)
            self.assertEqual(output.read_bytes(), saved)
            self.assertEqual(self.invoke(['reconcile', *paths, '--report', report_path])[0], 2)

    def test_partial_receipt_write_rolls_back_and_same_names_can_retry(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source, report, decisions, output = [root / n for n in
                                                  ('source', 'review', 'choices', 'merged')]
            source.write_bytes(blob({'port': 8080}))
            self.assertEqual(self.invoke(['reconcile', source, source, source,
                                         '--report', report])[0], 0)
            decisions.write_bytes(blob({
                'report_sha256': json.loads(report.read_bytes())['report_sha256'],
                'decisions': []}))
            receipt = Path(str(output) + '.receipt.json')
            original_open = cli._open_output

            class FailedWrite:
                def __init__(self, stream):
                    self.stream = stream

                def write(self, data):
                    self.stream.write(data[:8])
                    raise OSError('synthetic partial write')

                def close(self):
                    self.stream.close()

            def partial_write(path):
                stream = original_open(path)
                return FailedWrite(stream) if path == receipt else stream

            args = ['resolve', report, '--base', source, '--left', source, '--right', source,
                    '--decisions', decisions, '--output', output]
            with patch.object(cli, '_open_output', new=partial_write):
                code, out, err = self.invoke(args)
            self.assertEqual((code, out), (2, ''))
            self.assertEqual(json.loads(err)['error'], 'INVALID_INPUT')
            self.assertIn('request_id', json.loads(err))
            self.assertNotIn('synthetic partial write', err)
            self.assertFalse(output.exists())
            self.assertFalse(receipt.exists())
            self.assertEqual(self.invoke(args)[0], 0)
            self.assertEqual(self.invoke(['verify-output', output, '--receipt', receipt])[0], 0)

    def test_cli_private_errors_create_no_output(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            paths = [root / f'{side}.json' for side in ('base', 'left', 'right')]
            for path in paths:
                path.write_bytes(b'{}')
            report_path, decisions, output = [root / f'{s}.json' for s in
                                              ('review', 'decisions', 'merged')]
            self.assertEqual(self.invoke(['reconcile', *paths, '--report', report_path])[0], 0)
            report = json.loads(report_path.read_text())
            decisions.write_bytes(blob({'report_sha256': report['report_sha256'], 'decisions': []}))
            paths[0].write_bytes(b'{ }')
            args = ['resolve', report_path, '--base', paths[0], '--left', paths[1],
                    '--right', paths[2], '--decisions', decisions, '--output', output]
            code, out, err = self.invoke(args)
            self.assertEqual((code, out), (2, ''))
            self.assertNotIn(name, err)
            self.assertEqual(json.loads(err)['error'], 'INVALID_INPUT')
            self.assertIn('request_id', json.loads(err))
            self.assertEqual(json.loads(err)['message'],
                             'Review no longer matches the inputs or options. Run reconcile '
                             'again, then review and regenerate decisions before resolving.')
            self.assertFalse(output.exists())
            self.assertFalse(Path(str(output) + '.receipt.json').exists())

    def test_cli_receipt_collision_malformed_and_symlink_controls(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            paths = [root / f'{side}.json' for side in ('base', 'left', 'right')]
            for path in paths:
                path.write_bytes(b'{}')
            report, decisions, output = [root / f'{s}.json' for s in
                                         ('review', 'decisions', 'merged')]
            self.assertEqual(self.invoke(['reconcile', *paths, '--report', report])[0], 0)
            decisions.write_bytes(blob({'report_sha256': json.loads(report.read_text())['report_sha256'],
                                        'decisions': []}))
            args = ['resolve', report, '--base', paths[0], '--left', paths[1],
                    '--right', paths[2], '--decisions', decisions, '--output', output]
            receipt = Path(str(output) + '.receipt.json')
            receipt.write_text('keep')
            self.assertEqual(self.invoke(args)[0], 2)
            self.assertFalse(output.exists())
            self.assertEqual(receipt.read_text(), 'keep')
            receipt.unlink()
            output.symlink_to(root / 'absent.json')
            self.assertEqual(self.invoke(args)[0], 2)
            self.assertTrue(output.is_symlink())
            output.unlink()
            decisions.write_text('{"decisions": [], "decisions": []}')
            self.assertEqual(self.invoke(args)[0], 2)
            self.assertFalse(output.exists())
            for invalid_args in (['resolve', root / 'private', '--unknown'],
                                 ['reconcile', *paths, '--report']):
                code, out, err = self.invoke(invalid_args)
                self.assertEqual((code, out), (2, ''))
                self.assertEqual(json.loads(err)['error'], 'INVALID_INPUT')
                self.assertNotIn(name, err)
