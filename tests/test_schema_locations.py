"""Schema keywords are interpreted at schema locations, not inside instance data."""
import json
import unittest

from unitmerge.reconcile import SchemaSupportMissing, reconcile, resolve


class SchemaLocationTests(unittest.TestCase):
    def setUp(self):
        try:
            reconcile(b'{}', b'{}', b'{}', schema=b'{}')
        except SchemaSupportMissing:
            self.skipTest('optional schema extra absent')

    def materialize(self, instance, schema):
        raw = json.dumps(instance).encode()
        definition = json.dumps(schema).encode()
        report = reconcile(raw, raw, raw, schema=definition)
        return resolve(report, {'report_sha256': report['report_sha256'], 'decisions': []},
                       raw, raw, raw, schema=definition)['merged']

    def test_literal_reserved_keys_are_data(self):
        value = {'$ref': 'https://example.invalid/data', '$id': 'ordinary-id',
                 '$schema': 'a-data-label', '$dynamicRef': 'not-a-schema-reference'}
        self.assertEqual(self.materialize(value, {'const': value}), value)

    def test_keyword_named_properties_are_not_keywords(self):
        schema = {'type': 'object', 'properties': {'$id': {'type': 'integer'},
                  '$ref': {'type': 'string'}}, 'required': ['$id', '$ref']}
        self.assertEqual(self.materialize({'$id': 7, '$ref': 'label'}, schema),
                         {'$id': 7, '$ref': 'label'})

    def test_annotation_payloads_are_not_scanned_as_schemas(self):
        for keyword in ('default', 'examples', 'enum'):
            value = {'$id': 'data-id', '$ref': 'https://example.invalid/data'}
            payload = value if keyword == 'default' else [value]
            schema = {'type': 'object', keyword: payload}
            with self.subTest(keyword=keyword):
                self.assertEqual(self.materialize(value, schema), value)

    def test_remote_references_in_real_subschemas_are_still_refused(self):
        for schema in ({'$defs': {'unused': {'$ref': 'https://example.invalid/schema'}}},
                       {'properties': {'value': {'$id': 'new-resource'}}},
                       {'allOf': [{'$dynamicRef': 'https://example.invalid/anchor'}]}):
            with self.subTest(schema=schema), self.assertRaises(ValueError):
                self.materialize({}, schema)

    def test_referenced_literal_is_checked_when_used_as_a_schema(self):
        schema = {'const': {'$id': 'now-a-schema-resource'}, '$ref': '#/const'}
        with self.assertRaises(ValueError):
            self.materialize({'$id': 'now-a-schema-resource'}, schema)

    def test_local_reference_and_invalid_instance_controls(self):
        schema = {'$defs': {'value': {'type': 'integer'}}, '$ref': '#/$defs/value'}
        self.assertEqual(self.materialize(7, schema), 7)
        with self.assertRaises(ValueError):
            self.materialize('seven', schema)
