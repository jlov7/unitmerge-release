"""Exercise installed-style entry points and hostile local JSON boundaries."""
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from unitmerge import __version__, cli
from unitmerge.cli import main


class CommandTests(unittest.TestCase):
    def invoke(self, args):
        out, err = io.StringIO(), io.StringIO()
        with patch('sys.argv', ['unitmerge', *map(str, args)]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = main()
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def test_version_reports_the_installed_package(self):
        code, out, err = self.invoke(['--version'])
        self.assertEqual((code, out, err), (0, f'unitmerge {__version__}\n', ''))

    def test_demo_exercises_receipts_conflicts_counterexample_and_union(self):
        code, out, err = self.invoke(['--demo'])
        self.assertEqual((code, err), (0, ''))
        cases = json.loads(out)['cases']
        self.assertEqual(set(cases), {'matched', 'bad_digest', 'conflict', 'false_value'})
        self.assertEqual(cases['matched']['checked']['units']['max']['value'], 80)
        self.assertEqual(cases['bad_digest']['checked']['units']['max']['status'], 'unsupported')
        self.assertEqual(cases['conflict']['checked']['units']['max']['status'], 'conflict')
        self.assertEqual(cases['false_value']['checked']['units']['max']['value'], 900)
        self.assertTrue(all(c['same_as_union'] for c in cases.values()))
        self.assertFalse(cases['false_value']['checked']['evidence_receipts'][0]
                         ['semantic_entailment_established'])

    def test_sources_are_literal_utf8_text_and_rejected_receipts_survive(self):
        with tempfile.TemporaryDirectory() as name:
            packet, sources = Path(name) / 'packet.json', Path(name) / 'sources.json'
            text = 'Température: 80 °C'
            start = text.encode().index(b'80')
            payload = {'units': ['max'], 'sources': {'s': {'current': True}}, 'proposals': [
                {'unit_id': 'max', 'source_ref': 's', 'worker_id': 'w', 'value': 80,
                 'evidence': {'sha256': hashlib.sha256(text.encode()).hexdigest(),
                              'start': start, 'end': start + 2, 'quote': '80'}}]}
            packet.write_text(json.dumps(payload), encoding='utf-8')
            sources.write_text(json.dumps({'s': text}), encoding='utf-8')
            code, out, err = self.invoke([packet, '--sources', sources])
            self.assertEqual((code, err), (0, ''))
            self.assertEqual(json.loads(out)['evidence_receipts'][0]['status'], 'MATCHED_BYTES')
            sources.write_text(json.dumps({'s': 'a/path/is/literal/text'}), encoding='utf-8')
            self.assertEqual(json.loads(self.invoke([packet, '--sources', sources])[1])
                             ['evidence_receipts'][0]['reason'], 'DIGEST_MISMATCH')

    def test_bad_input_returns_structured_private_error(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / 'private-input.json'
            for raw in ('{"units": [], "units": []}', '{"x": NaN}', '[' * 70 + '0' + ']' * 70,
                        '"\\ud800"', '{invalid', '[]'):
                with self.subTest(raw=raw[:30]):
                    path.write_text(raw, encoding='utf-8')
                    code, out, err = self.invoke([path])
                    self.assertEqual((code, out), (2, ''))
                    error = json.loads(err)
                    self.assertEqual(error['error'], 'INVALID_INPUT')
                    self.assertRegex(error['request_id'], r'^[0-9a-f]{16}$')
                    self.assertNotIn(str(path), err)
                    self.assertNotIn('Traceback', err)
            code, out, err = self.invoke([Path(name) / 'missing.json'])
            self.assertEqual((code, out), (2, ''))
            self.assertEqual(json.loads(err)['error'], 'INVALID_INPUT')

    def test_packet_syntax_errors_are_structured_and_private(self):
        for args in ([], ['--private-tenant-token=synthetic-secret'],
                     ['--demo', '/private/synthetic-packet.json']):
            with self.subTest(args=args):
                code, out, err = self.invoke(args)
                self.assertEqual((code, out), (2, ''))
                error = json.loads(err)
                self.assertEqual(error['error'], 'INVALID_INPUT')
                self.assertEqual(error['message'], 'Check command syntax with --help.')
                self.assertRegex(error['request_id'], r'^[0-9a-f]{16}$')
                self.assertNotIn('synthetic', err)

    def invoke_process(self, args):
        script = ("import sys; sys.path.insert(0, sys.argv.pop(1)); "
                  "from unitmerge.cli import main; raise SystemExit(main())")
        try:
            # subprocess.run kills and reaps its child when the timeout expires.
            return subprocess.run(
                [sys.executable, '-I', '-c', script,
                 str(Path(cli.__file__).resolve().parents[1]), *map(str, args)],
                capture_output=True, text=True, timeout=2, check=False)
        except subprocess.TimeoutExpired:
            self.fail('input did not return within two seconds')

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'FIFOs require os.mkfifo')
    def test_fifo_inputs_are_prompt_private_refusals_in_every_mode(self):
        from unitmerge.reconcile import reconcile

        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            config, packet, sources, report, decisions, policy, schema, receipt = [
                root / (label + '.json') for label in
                ('config', 'packet', 'sources', 'report', 'decisions', 'policy',
                 'schema', 'receipt')]
            config.write_bytes(b'{}')
            packet.write_text('{"units":["x"],"sources":{},"proposals":[]}')
            sources.write_text('{}')
            review = reconcile(b'{}', b'{}', b'{}')
            report.write_text(json.dumps(review))
            decisions.write_text(json.dumps({'report_sha256': review['report_sha256'],
                                            'decisions': []}))
            policy.write_text('{}')
            schema.write_text('{"type":"object"}')
            receipt.write_text('{}')
            output = root / 'output.json'
            fifo = root / 'private-marker.fifo'
            os.mkfifo(fifo)
            alias = root / 'private-marker-link'
            alias.symlink_to(fifo)
            inputs = {config, packet, sources, report, decisions, policy, schema, receipt}
            commands = [
                ('packet', [packet]),
                ('sources', [packet, '--sources', sources]),
                ('reconcile', ['reconcile', config, config, config, '--array-policy',
                               policy, '--schema', schema, '--report', output]),
                ('resolve', ['resolve', report, '--base', config, '--left', config,
                             '--right', config, '--decisions', decisions, '--array-policy',
                             policy, '--schema', schema, '--output', output]),
                ('review', ['review', report]),
                ('template', ['decisions-template', report, '--output', output]),
                ('verify', ['verify-output', config, '--receipt', receipt]),
            ]
            for command, args in commands:
                for index, value in enumerate(args):
                    if value not in inputs:
                        continue
                    for target in (fifo, alias):
                        with self.subTest(command=command, index=index, link=target == alias):
                            rejected = [*args[:index], target, *args[index + 1:]]
                            result = self.invoke_process(rejected)
                            self.assertEqual((result.returncode, result.stdout), (2, ''))
                            error = json.loads(result.stderr)
                            self.assertEqual(error['error'], 'INVALID_INPUT')
                            self.assertRegex(error['request_id'], r'^[0-9a-f]{16}$')
                            self.assertNotIn(name, result.stderr)
                            self.assertNotIn('private-marker', result.stderr)
                            self.assertNotIn('Traceback', result.stderr)
                            self.assertFalse(output.exists())
                            self.assertFalse(Path(str(output) + '.receipt.json').exists())

    @unittest.skipUnless(hasattr(os, 'symlink'), 'symlinks require os.symlink')
    def test_regular_input_symlinks_preserve_exact_bytes(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source, link, report = [root / label for label in
                                    ('source.json', 'source-link.json', 'review.json')]
            raw = b'{"answer": 42}\r\n'
            source.write_bytes(raw)
            link.symlink_to(source)
            code, _, err = self.invoke(['reconcile', link, link, link, '--report', report])
            self.assertEqual((code, err), (0, ''))
            review = json.loads(report.read_bytes())
            self.assertTrue(all(value['sha256'] == hashlib.sha256(raw).hexdigest()
                                for value in review['inputs'].values()))
            report_link = root / 'review-link.json'
            report_link.symlink_to(report)
            code, out, err = self.invoke(['review', report_link])
            self.assertEqual((code, err), (0, ''))
            self.assertIn('No conflicts', out)

    def test_bounded_reader_rejects_oversize_file(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / 'large.json'
            path.write_bytes(b' ' * 65)
            with patch('unitmerge.cli.MAX_INPUT_BYTES', 64, create=True):
                code, out, err = self.invoke([path])
            self.assertEqual((code, out), (2, ''))
            self.assertEqual(json.loads(err)['error'], 'INVALID_INPUT')

    def test_unreadable_files_have_actionable_private_diagnostic(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            packet = directory / 'packet.json'
            packet.write_text('{"units": ["x"], "sources": {}, "proposals": []}',
                              encoding='utf-8')
            for args in ([directory / 'missing.json'], [directory],
                         [packet, '--sources', directory / 'missing-sources.json']):
                with self.subTest(args=args):
                    code, out, err = self.invoke(args)
                    self.assertEqual((code, out), (2, ''))
                    error = json.loads(err)
                    self.assertEqual(error['error'], 'INVALID_INPUT')
                    self.assertEqual(error['message'],
                                     'Check that each input file exists and is readable.')
                    self.assertRegex(error['request_id'], r'^[0-9a-f]{16}$')
                    self.assertNotIn(name, err)
                    self.assertNotIn('Traceback', err)


if __name__ == '__main__':
    unittest.main()
