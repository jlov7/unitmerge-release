"""Read-only resolution checks must explain blockers without choosing or writing."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from unitmerge.reconcile import ReviewMismatch, decisions_template, reconcile, resolve


def fixture():
    base = {'cache': {'ttl': 60, 'entries': 100}, 'logging': 'info', 'secret': 'do-not-print'}
    left = {'cache': {'ttl': 120, 'entries': 100}, 'logging': 'debug', 'secret': 'do-not-print'}
    right = {'cache': {'ttl': 30, 'entries': 150}, 'logging': 'warning', 'secret': 'do-not-print'}
    return tuple(json.dumps(x).encode() for x in (base, left, right))

def choices(report, take='right'):
    result = decisions_template(report)
    for item in result['decisions']:
        item['take'] = take
    return result

class PreviewTests(unittest.TestCase):

    def preview(self, *args, **kwargs):
        from unitmerge.preflight import preview
        return preview(*args, **kwargs)

    def test_incomplete_template_identifies_every_pending_path(self):
        raw = fixture()
        report = reconcile(*raw)
        result = self.preview(report, decisions_template(report), *raw)
        self.assertEqual(result['status'], 'NEEDS_DECISIONS')
        self.assertEqual(result['pending_paths'], ['/cache/ttl', '/logging'])
        self.assertEqual(result['resolved_count'], 0)
        self.assertEqual(result['schema_status'], 'NOT_CHECKED')
        self.assertNotIn('do-not-print', json.dumps(result))

    def test_missing_choices_are_pending_not_implicitly_selected(self):
        raw = fixture()
        report = reconcile(*raw)
        selected = choices(report)
        selected['decisions'].pop()
        result = self.preview(report, selected, *raw)
        self.assertEqual(result['pending_paths'], ['/logging'])
        self.assertEqual(result['resolved_count'], 1)
        self.assertEqual(result['status'], 'NEEDS_DECISIONS')

    def test_complete_choices_match_the_real_resolver(self):
        raw = fixture()
        report = reconcile(*raw)
        selected = choices(report)
        result = self.preview(report, selected, *raw)
        self.assertEqual(result['status'], 'READY')
        self.assertEqual(result['merged_content_sha256'], resolve(report, selected, *raw)['receipt']['merged_content_sha256'])
        self.assertEqual(result['schema_status'], 'NOT_REQUESTED')
        self.assertNotIn('do-not-print', json.dumps(result))

    def test_schema_failure_gives_paths_and_keywords_not_values(self):
        raw = fixture()
        schema = json.dumps({'type': 'object', 'properties': {'cache': {'properties': {'ttl': {'maximum': 90}}}, 'logging': {'enum': ['warning', 'info']}}}).encode()
        report = reconcile(*raw, schema=schema)
        selected = choices(report, 'left')
        result = self.preview(report, selected, *raw, schema=schema)
        self.assertEqual(result['status'], 'SCHEMA_REJECTED')
        self.assertEqual(result['schema_issues'], [{'path': '/cache/ttl', 'keyword': 'maximum'}, {'path': '/logging', 'keyword': 'enum'}])
        self.assertNotIn('do-not-print', json.dumps(result))
        self.assertNotIn('debug', json.dumps(result))
        self.assertIsNone(result['merged_content_sha256'])
        with self.assertRaises(ValueError):
            resolve(report, selected, *raw, schema=schema)

    def test_schema_success_does_not_claim_semantic_correctness(self):
        raw = fixture()
        schema = b'{"type":"object"}'
        report = reconcile(*raw, schema=schema)
        result = self.preview(report, choices(report), *raw, schema=schema)
        self.assertEqual(result['schema_status'], 'PASS')
        self.assertFalse(result['semantic_correctness_established'])

    def test_stale_bytes_rejected_even_with_pending_choices(self):
        raw = fixture()
        report = reconcile(*raw)
        with self.assertRaises(ReviewMismatch):
            self.preview(report, decisions_template(report), raw[0] + b' ', *raw[1:])

    def test_changed_schema_and_tampered_report_are_rejected(self):
        raw = fixture()
        schema = b'{"type":"object"}'
        report = reconcile(*raw, schema=schema)
        with self.assertRaises(ReviewMismatch):
            self.preview(report, choices(report), *raw, schema=schema + b' ')
        selected = choices(report)
        report['conflicts'][0]['left']['value'] = 12
        with self.assertRaises(ValueError):
            self.preview(report, selected, *raw, schema=schema)

    def test_invalid_choices_do_not_hide_behind_pending_choices(self):
        raw = fixture()
        report = reconcile(*raw)
        good = choices(report)
        mutations = [dict(good, extra=True), dict(good, report_sha256='0' * 64), dict(good, decisions=[good['decisions'][0]] * 2), dict(good, decisions=[{'path': '/unknown', 'take': 'right'}]), dict(good, decisions=[{'path': '/logging', 'take': True}]), dict(good, decisions=[{'path': '/logging', 'take': 'custom'}]), dict(good, decisions=[{'path': [], 'take': 'left'}])]
        for bad in mutations:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.preview(report, bad, *raw)

    def test_root_null_delete_and_keyed_array_choices(self):
        fixtures = [((b'0', b'null', b'1'), {}), ((b'{"x":1}', b'{}', b'{"x":2}'), {}), ((b'{"rows":[{"id":"a","x":1}]}', b'{"rows":[{"id":"a","x":2}]}', b'{"rows":[{"id":"a","x":3}]}'), {'array_policy': {'/rows': 'id'}})]
        for raw, kwargs in fixtures:
            report = reconcile(*raw, **kwargs)
            for take in ('base', 'left', 'right'):
                selected = choices(report, take)
                with self.subTest(raw=raw, take=take):
                    observed = self.preview(report, selected, *raw, **kwargs)
                    self.assertEqual(observed['merged_content_sha256'], resolve(report, selected, *raw, **kwargs)['receipt']['merged_content_sha256'])

    def test_no_inputs_mutated(self):
        raw = fixture()
        report = reconcile(*raw)
        selected = choices(report)
        saved = copy.deepcopy((report, selected))
        self.preview(report, selected, *raw)
        self.assertEqual((report, selected), saved)

    def test_schema_diagnostics_are_bounded_and_pointer_escaped(self):
        raw = (json.dumps({'a/b~x': [None] * 40}).encode(),) * 3
        schema = b'{"properties":{"a/b~x":{"items":{"type":"integer"}}}}'
        report = reconcile(*raw, schema=schema)
        result = self.preview(report, choices(report), *raw, schema=schema)
        self.assertEqual(result['status'], 'SCHEMA_REJECTED')
        self.assertLessEqual(len(result['schema_issues']), 16)
        self.assertTrue(result['schema_issues_truncated'])
        self.assertTrue(all(x['path'].startswith('/a~1b~0x/') for x in result['schema_issues']))

    def test_schema_diagnostic_limit_marks_only_additional_errors(self):
        schema = b'{"items":{"type":"integer"}}'
        for count in (16, 17):
            raw = (json.dumps([None] * count).encode(),) * 3
            report = reconcile(*raw, schema=schema)
            with self.subTest(count=count):
                result = self.preview(report, choices(report), *raw, schema=schema)
                self.assertEqual(len(result['schema_issues']), 16)
                self.assertEqual(result['schema_issues_truncated'], count == 17)

    def test_cli_schema_rejection_and_invalid_reference_are_private_and_read_only(self):
        cases = [
            (b'{"properties":{"secret":{"const":"private-required-value"}}}', 1),
            (b'{"description":"private-schema-value","$ref":"#/description/x"}', 2),
        ]
        for schema, expected_code in cases:
            with self.subTest(schema=schema), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                raw = fixture()
                report = reconcile(*raw, schema=schema)
                for side, data in zip(('base', 'left', 'right'), raw):
                    (root / f'{side}.json').write_bytes(data)
                (root / 'schema.json').write_bytes(schema)
                (root / 'report.json').write_text(json.dumps(report))
                (root / 'choices.json').write_text(json.dumps(choices(report)))
                before = {p.name: p.read_bytes() for p in root.iterdir()}
                cmd = [sys.executable, '-m', 'unitmerge.cli', 'preview',
                       str(root / 'report.json')]
                for option in ('base', 'left', 'right', 'schema'):
                    cmd.extend(['--' + option, str(root / f'{option}.json')])
                cmd.extend(['--decisions', str(root / 'choices.json')])
                result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, expected_code, result.stderr)
                self.assertLess(len(result.stdout + result.stderr), 4096)
                for private in ('do-not-print', 'private-required-value',
                                'private-schema-value', str(root), 'Traceback'):
                    self.assertNotIn(private, result.stdout + result.stderr)
                if expected_code == 1:
                    self.assertEqual(result.stderr, '')
                    observed = json.loads(result.stdout)
                    self.assertEqual(observed['status'], 'SCHEMA_REJECTED')
                    self.assertEqual(observed['schema_issues'],
                                     [{'path': '/secret', 'keyword': 'const'}])
                else:
                    self.assertEqual(result.stdout, '')
                    error = json.loads(result.stderr)
                    self.assertEqual(error['error'], 'INVALID_INPUT')
                    self.assertRegex(error['request_id'], r'^[0-9a-f]{16}$')
                self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, before)

    def test_cli_missing_schema_extra_refuses_without_writing(self):
        import contextlib
        import io

        from unitmerge.preflight import main

        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            raw = fixture()
            schema = b'{"type":"object"}'
            report = reconcile(*raw, schema=schema)
            for side, data in zip(('base', 'left', 'right'), raw):
                (root / f'{side}.json').write_bytes(data)
            (root / 'schema.json').write_bytes(schema)
            (root / 'report.json').write_text(json.dumps(report))
            (root / 'choices.json').write_text(json.dumps(choices(report)))
            args = [str(root / 'report.json')]
            for option in ('base', 'left', 'right', 'schema'):
                args.extend(['--' + option, str(root / f'{option}.json')])
            args.extend(['--decisions', str(root / 'choices.json')])
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            out, err = io.StringIO(), io.StringIO()
            with patch.dict(sys.modules, {'jsonschema': None}), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(args)
            self.assertEqual((code, out.getvalue()), (2, ''))
            error = json.loads(err.getvalue())
            self.assertEqual(error['error'], 'INVALID_INPUT')
            self.assertEqual(error['message'], 'Install unitmerge[schema] before using --schema.')
            self.assertRegex(error['request_id'], r'^[0-9a-f]{16}$')
            self.assertLess(len(err.getvalue()), 512)
            self.assertNotIn(str(root), err.getvalue())
            self.assertNotIn('do-not-print', err.getvalue())
            self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, before)

    def test_invalid_remote_schema_still_refused(self):
        raw = fixture()
        with self.assertRaises(ValueError):
            reconcile(*raw, schema=b'{"$ref":"https://example.invalid/schema"}')

    def test_cli_read_only_exit_codes_and_repeated_use(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            raw = fixture()
            for side, data in zip(('base', 'left', 'right'), raw):
                (root / f'{side}.json').write_bytes(data)
            report = reconcile(*raw)
            (root / 'report.json').write_text(json.dumps(report))
            choice = root / 'choices.json'
            choice.write_text(json.dumps(decisions_template(report)))
            cmd = [sys.executable, '-m', 'unitmerge.cli', 'preview', str(root / 'report.json'), '--base', str(root / 'base.json'), '--left', str(root / 'left.json'), '--right', str(root / 'right.json'), '--decisions', str(choice)]
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=10, env=os.environ.copy())
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(json.loads(result.stdout)['status'], 'NEEDS_DECISIONS')
            self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, before)
            choice.write_text(json.dumps(choices(report)))
            for _ in range(2):
                result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=10, env=os.environ.copy())
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)['status'], 'READY')
            (root / 'base.json').write_bytes(raw[0] + b' ')
            result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=10, env=os.environ.copy())
            self.assertEqual(result.returncode, 2)
            self.assertNotIn('do-not-print', result.stdout + result.stderr)
            self.assertEqual({p.name for p in root.iterdir()}, set(before))
