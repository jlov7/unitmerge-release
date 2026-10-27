"""Independent expectations for the optional configuration review tools."""
import copy
import hashlib
import itertools
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_cli

from unitmerge import reconcile as api


def raw(value):
    return json.dumps(value, ensure_ascii=False).encode()


class ReviewToolsTests(unittest.TestCase):
    def test_template_exact_pointers_unresolved_and_stale(self):
        for docs, paths in [((0, 1, 2), ['']),
                            (({'': 0, '~/': 0, '雪': 0}, {'': 1, '~/': 1, '雪': 1},
                              {'': 2, '~/': 2, '雪': 2}), ['/', '/~0~1', '/雪'])]:
            inputs = tuple(map(raw, docs))
            report = api.reconcile(*inputs)
            template = api.decisions_template(report)
            self.assertEqual([d['path'] for d in template['decisions']], paths)
            self.assertEqual([d['take'] for d in template['decisions']], ['UNRESOLVED'] * len(paths))
            with self.assertRaises(ValueError):
                api.resolve(report, template, *inputs)
            for choice in template['decisions']:
                choice['take'] = 'right'
            self.assertEqual(api.resolve(report, template, *inputs)['merged'], docs[2])
            with self.assertRaises(ValueError):
                api.resolve(report, template, inputs[0] + b' ', *inputs[1:])

    def test_readable_review_inert_values_missing_and_null(self):
        report = api.reconcile(raw({'x': 0, 'a': [0]}), raw({'a': [1]}),
                               raw({'x': None, 'a': ['<script>\u001b[2J']}))
        saved = copy.deepcopy(report)
        rendered = api.render_review(report)
        for expected in ('/x', '/a', 'base:', 'left:', 'right:', 'MISSING', 'null',
                         '<script>', r'\u001b'):
            self.assertIn(expected, rendered)
        self.assertNotIn('\u001b', rendered)
        self.assertEqual(report, saved)
        self.assertIn('(root)', api.render_review(api.reconcile(b'0', b'1', b'2')))
        report['conflicts'][0]['path'] = '/forged'
        with self.assertRaises(ValueError):
            api.render_review(report)

    def test_verify_output_distinguishes_bytes_content_and_refuses_bad_receipt(self):
        inputs = (b'{}', b'{"x":1}', b'{}')
        report = api.reconcile(*inputs)
        result = api.resolve(report, api.decisions_template(report), *inputs)
        output = b'{"x": 1}\n'
        receipt = {**result['receipt'], 'output_bytes_sha256': hashlib.sha256(output).hexdigest()}
        for data, expected in [(output, 'MATCH'), (b'{ "x" : 1 }', 'BYTES_DIFFER'),
                               (b'{"x":2}', 'CONTENT_DIFFER')]:
            self.assertEqual(api.verify_output(data, receipt)['status'], expected)
        for invalid in [{}, {**receipt, 'extra': 1}, {**receipt, 'inputs': []},
                        {**receipt, 'semantic_correctness_established': True},
                        {**receipt, 'merged_content_sha256': 'bad'}]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                api.verify_output(output, invalid)

    def test_keyed_arrays_disjoint_same_id_deletion_order_and_binding(self):
        policy = {'/routes': 'id'}
        docs = ({'routes': [{'id': 'b', 'v': 0}, {'id': 'a', 'v': 0}]},
                {'routes': [{'id': 'a', 'v': 1}, {'id': 'b', 'v': 0}, {'id': 'c', 'v': 3}]},
                {'routes': [{'id': 'b', 'v': 2}, {'id': 'a', 'v': 0}]})
        inputs = tuple(map(raw, docs))
        self.assertEqual(len(api.reconcile(*inputs)['conflicts']), 1)
        report = api.reconcile(*inputs, array_policy=policy)
        self.assertEqual(report['conflicts'], [])
        result = api.resolve(report, api.decisions_template(report), *inputs, array_policy=policy)
        self.assertEqual(result['merged'], {'routes': [{'id': 'a', 'v': 1},
                         {'id': 'b', 'v': 2}, {'id': 'c', 'v': 3}]})
        self.assertEqual(result['receipt']['options'], report['options'])
        with self.assertRaises(ValueError):
            api.resolve(report, api.decisions_template(report), *inputs)
        # Even disjoint fields of one identity require a whole-entry choice.
        inputs = tuple(map(raw, ([{'id': '~/雪', 'a': 0, 'b': 0}],
                                 [{'id': '~/雪', 'a': 1, 'b': 0}],
                                 [{'id': '~/雪', 'a': 0, 'b': 1}])))
        report = api.reconcile(*inputs, array_policy={'': 'id'})
        self.assertEqual([c['path'] for c in report['conflicts']], ['/~0~1雪'])
        choice = api.decisions_template(report)
        choice['decisions'][0]['take'] = 'left'
        self.assertEqual(api.resolve(report, choice, *inputs, array_policy={'': 'id'})['merged'],
                         json.loads(inputs[1]))
        inputs = (raw([{'id': 'a', 'v': 0}]), b'[]', raw([{'id': 'a', 'v': 1}]))
        report = api.reconcile(*inputs, array_policy={'': 'id'})
        self.assertFalse(report['conflicts'][0]['left']['present'])
        choice = api.decisions_template(report)
        choice['decisions'][0]['take'] = 'left'
        self.assertEqual(api.resolve(report, choice, *inputs, array_policy={'': 'id'})['merged'], [])

    def test_keyed_arrays_reject_ambiguous_identities_and_paths_even_unchanged(self):
        for value in [[{'id': 'a'}, {'id': 'a'}], [{}], [{'id': 1}], [{'id': ''}], [None]]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                api.reconcile(raw(value), raw(value), raw(value), array_policy={'': 'id'})
        for policy in [{'/absent': 'id'}, {'bad': 'id'}, {'/~2': 'id'}, {'': ''},
                       {'': 'id', '/nested': 'id'}]:
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                api.reconcile(b'[]', b'[]', b'[]', array_policy=policy)
        report = api.reconcile(raw([{'id': 'z'}, {'id': 'a'}]),
                               raw([{'id': 'a'}, {'id': 'z'}]),
                               raw([{'id': 'z'}, {'id': 'a'}]), array_policy={'': 'id'})
        self.assertEqual(report['automatic']['value'], [{'id': 'a'}, {'id': 'z'}])
        result = api.resolve(report, api.decisions_template(report),
                             raw([{'id': 'z'}, {'id': 'a'}]), raw([{'id': 'a'}, {'id': 'z'}]),
                             raw([{'id': 'z'}, {'id': 'a'}]), array_policy={'': 'id'})
        self.assertEqual(result['merged'], [{'id': 'a'}, {'id': 'z'}])

    def test_keyed_array_independent_presence_value_oracle(self):
        # Missing, old and new whole entries: independently choose the changed
        # side, or explicitly choose right when both diverged from the ancestor.
        for base, left, right in itertools.product((None, 0, 1), repeat=3):
            def entries(value):
                return [] if value is None else [{'id': 'x', 'value': value}]
            inputs = tuple(raw(entries(value)) for value in (base, left, right))
            conflict = left != right and base != left and base != right
            expected = right if conflict or base == left else left
            report = api.reconcile(*inputs, array_policy={'': 'id'})
            self.assertEqual(len(report['conflicts']), int(conflict))
            choices = api.decisions_template(report)
            for choice in choices['decisions']:
                choice['take'] = 'right'
            self.assertEqual(api.resolve(report, choices, *inputs,
                                        array_policy={'': 'id'})['merged'], entries(expected))

    def test_schema_valid_invalid_local_refs_remote_refusal_and_stale_binding(self):
        schema = raw({'$schema': 'https://json-schema.org/draft/2020-12/schema',
                      '$defs': {'port': {'type': 'integer', 'minimum': 1, 'maximum': 65535}},
                      'type': 'object', 'properties': {'port': {'$ref': '#/$defs/port'}},
                      'required': ['port'], 'additionalProperties': False})
        inputs = (b'{"port":80}', b'{"port":8080}', b'{"port":80}')
        report = api.reconcile(*inputs, schema=schema)
        result = api.resolve(report, api.decisions_template(report), *inputs, schema=schema)
        self.assertEqual(result['merged'], {'port': 8080})
        self.assertEqual(result['receipt']['options']['schema_sha256'], hashlib.sha256(schema).hexdigest())
        for changed in (None, schema + b' '):
            with self.assertRaises(ValueError):
                api.resolve(report, api.decisions_template(report), *inputs, schema=changed)
        bad = (inputs[0], b'{"port":99999}', inputs[2])
        report = api.reconcile(*bad, schema=schema)
        with self.assertRaises(ValueError):
            api.resolve(report, api.decisions_template(report), *bad, schema=schema)
        for schema_value in [{'$ref': 'https://example.invalid/a'}, {'$ref': 'file:///secret'},
                             {'$dynamicRef': 'other.json#x'}, {'type': 'nonsense'},
                             {'$schema': 'https://json-schema.org/draft-07/schema'}]:
            with self.subTest(schema=schema_value), self.assertRaises(ValueError):
                api.reconcile(*inputs, schema=raw(schema_value))
        missing_ref = raw({'$ref': '#/$defs/absent'})
        report = api.reconcile(*inputs, schema=missing_ref)
        with self.assertRaises(ValueError):
            api.resolve(report, api.decisions_template(report), *inputs, schema=missing_ref)
        cross_field = raw({'if': {'properties': {'port': {'const': 443}}},
                           'then': {'properties': {'tls': {'const': True}}, 'required': ['tls']}})
        inputs = (b'{"port":80,"tls":false}', b'{"port":443,"tls":false}',
                  b'{"port":80,"tls":false}')
        report = api.reconcile(*inputs, schema=cross_field)
        with self.assertRaises(ValueError):
            api.resolve(report, api.decisions_template(report), *inputs, schema=cross_field)

    def test_schema_reference_targets_must_be_valid_schemas(self):
        inputs = (raw({'private': 'EXAMPLE_VALUE'}),) * 3
        schemas = [{'$ref': '#/title', 'title': 'abc'},
                   *({'$ref': '#/default', 'default': value}
                     for value in (None, 42, [], [True], {'type': 'wrong'},
                                   {'maximum': 'wrong'}, {'$ref': '#/title'})),
                   {'$dynamicRef': '#/title', 'title': 'abc'}]
        for value in schemas:
            if value.get('default') == {'$ref': '#/title'}:
                value['title'] = 'abc'
            with self.subTest(schema=value):
                schema = raw(value)
                report = api.reconcile(*inputs, schema=schema)
                with self.assertRaises(ValueError):
                    api.resolve(report, api.decisions_template(report), *inputs, schema=schema)

    def test_schema_pointer_through_scalar_is_a_value_error(self):
        inputs = (raw({'private': 'EXAMPLE_VALUE'}),) * 3
        for intermediate in (None, False, 42, 1.25, 'text'):
            with self.subTest(intermediate=intermediate):
                schema = raw({'$ref': '#/default/child', 'default': intermediate})
                report = api.reconcile(*inputs, schema=schema)
                with self.assertRaises(ValueError):
                    api.resolve(report, api.decisions_template(report), *inputs, schema=schema)

    def test_schema_reference_validation_preserves_literals_anchors_and_cycles(self):
        for value, schema in [
                ({'$ref': '#/absent'}, {'const': {'$ref': '#/absent'}}),
                ({}, {'default': {'type': 'object'}, '$ref': '#/default'}),
                ({}, {'default': True, '$ref': '#/default'}),
                ({}, {'$defs': {'object': {'$anchor': 'object', 'type': 'object'}},
                      '$ref': '#object'}),
                ({'child': {}}, {'type': 'object', 'properties': {'child': {'$ref': '#'}}})]:
            with self.subTest(schema=schema):
                inputs, encoded = (raw(value),) * 3, raw(schema)
                report = api.reconcile(*inputs, schema=encoded)
                self.assertEqual(api.resolve(report, api.decisions_template(report),
                                             *inputs, schema=encoded)['merged'], value)

    def test_verify_output_accepts_union_larger_than_any_input(self):
        inputs = tuple(raw({key: 'x' * 200}) for key in ('a', 'b', 'c'))
        # The common base entry is deleted on both sides, leaving b and c.
        with patch('unitmerge.reconcile.MAX_INPUT_BYTES', 256):
            report = api.reconcile(*inputs)
            result = api.resolve(report, api.decisions_template(report), *inputs)
            output = raw(result['merged'])
            self.assertGreater(len(output), 256)
            receipt = {**result['receipt'], 'output_bytes_sha256': hashlib.sha256(output).hexdigest()}
            self.assertEqual(api.verify_output(output, receipt)['status'], 'MATCH')


class ReviewToolCommandTests(unittest.TestCase):
    invoke = test_cli.CommandTests.invoke

    def test_cli_invalid_schema_reference_is_private_and_writes_nothing(self):
        for value in ({'$ref': '#/title', 'title': 'abc'},
                      {'$ref': '#/default', 'default': {'type': 'wrong'}},
                      {'$ref': '#/default', 'default': {'maximum': 'wrong'}}):
            with self.subTest(schema=value), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                source, schema = root / 'input', root / 'schema'
                source.write_bytes(raw({'private': 'EXAMPLE_VALUE'}))
                schema.write_bytes(raw(value))
                report, choices, output = (root / s for s in ('report', 'choices', 'output'))
                self.assertEqual(self.invoke(['reconcile', source, source, source,
                                             '--schema', schema, '--report', report])[0], 0)
                self.assertEqual(self.invoke(['decisions-template', report,
                                             '--output', choices])[0], 0)
                code, out, err = self.invoke(['resolve', report, '--base', source,
                    '--left', source, '--right', source, '--schema', schema,
                    '--decisions', choices, '--output', output])
                self.assertEqual((code, out), (2, ''))
                self.assertEqual(json.loads(err)['error'], 'INVALID_INPUT')
                self.assertTrue(json.loads(err)['request_id'])
                for private in ('EXAMPLE_VALUE', str(root), 'Traceback'):
                    self.assertNotIn(private, err)
                self.assertFalse(output.exists())
                self.assertFalse(Path(str(output) + '.receipt.json').exists())

    def test_cli_first_use_and_schema_rejection_writes_nothing(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for side, value in [('base', {'port': 80}), ('left', {'port': 99999}),
                                ('right', {'port': 81})]:
                (root / side).write_bytes(raw(value))
            schema = root / 'schema'
            schema.write_bytes(raw({'properties': {'port': {'maximum': 65535}}}))
            report, choices, output = (root / s for s in ('report', 'choices', 'output'))
            args = ['reconcile', root / 'base', root / 'left', root / 'right',
                    '--schema', schema, '--report', report]
            self.assertEqual(self.invoke(args)[0], 0)
            self.assertEqual(self.invoke(['review', report])[0], 0)
            self.assertEqual(self.invoke(['decisions-template', report, '--output', choices])[0], 0)
            resolve = ['resolve', report, '--base', root / 'base', '--left', root / 'left',
                       '--right', root / 'right', '--schema', schema, '--decisions', choices,
                       '--output', output]
            self.assertEqual(self.invoke(resolve)[0], 2)
            decision = json.loads(choices.read_bytes())
            decision['decisions'][0]['take'] = 'left'
            choices.write_bytes(raw(decision))
            self.assertEqual(self.invoke(resolve)[0], 2)
            self.assertFalse(output.exists())
            self.assertFalse(Path(str(output) + '.receipt.json').exists())
            decision['decisions'][0]['take'] = 'right'
            choices.write_bytes(raw(decision))
            self.assertEqual(self.invoke(resolve)[0], 0)
            receipt = Path(str(output) + '.receipt.json')
            self.assertEqual(self.invoke(['verify-output', output, '--receipt', receipt])[0], 0)
            output.write_bytes(b'{"port":81}')
            code, out, err = self.invoke(['verify-output', output, '--receipt', receipt])
            self.assertEqual((code, err), (1, ''))
            self.assertEqual(json.loads(out)['status'], 'BYTES_DIFFER')
            receipt.write_text('{"private":"do not disclose"}')
            code, out, err = self.invoke(['verify-output', output, '--receipt', receipt])
            self.assertEqual((code, out), (2, ''))
            self.assertNotIn('private', err)
            self.assertEqual(receipt.read_text(), '{"private":"do not disclose"}')

    def test_missing_schema_extra_fails_privately(self):
        import builtins
        original = builtins.__import__
        def without_extra(name, *args, **kwargs):
            if name == 'jsonschema':
                raise ImportError('not installed')
            return original(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=without_extra), self.assertRaises(ValueError):
            api.reconcile(b'{}', b'{}', b'{}', schema=b'{}')
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            input_file, schema = root / 'input', root / 'schema'
            input_file.write_text('{}')
            schema.write_text('{}')
            with patch('builtins.__import__', side_effect=without_extra):
                code, out, err = self.invoke(['reconcile', input_file, input_file, input_file,
                                             '--schema', schema, '--report', root / 'report'])
            self.assertEqual((code, out), (2, ''))
            self.assertEqual(json.loads(err)['message'],
                             'Install unitmerge[schema] before using --schema.')
            self.assertFalse((root / 'report').exists())
