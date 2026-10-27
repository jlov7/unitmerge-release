import copy
import hashlib
import importlib.util
import itertools
import unittest

from unitmerge.core import MergeInputError


class EvidenceContract(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('unitmerge.evidence'),
                             'Missing executable source-evidence API')
        from unitmerge.evidence import checked_merge
        self.run_merge = checked_merge
        self.blob = 'Température: 80 °C'.encode()
        quote = '80'
        start = self.blob.index(quote.encode())
        self.payload = {'units': ['max'], 'sources': {'s': {'current': True}},
                        'proposals': [{'unit_id': 'max', 'value': 80, 'source_ref': 's',
                                       'worker_id': 'a', 'evidence': {
                                           'sha256': hashlib.sha256(self.blob).hexdigest(),
                                           'start': start, 'end': start + 2, 'quote': quote}}]}

    def test_unicode_byte_span_checked_but_not_semantically_certified(self):
        result = self.run_merge(self.payload, {'s': self.blob})
        self.assertEqual(result['units']['max']['value'], 80)
        self.assertEqual(result['evidence_receipts'][0]['status'], 'MATCHED_BYTES')
        self.assertFalse(result['evidence_receipts'][0]['semantic_entailment_established'])

    def test_unsupported_value_can_still_have_matching_source_bytes(self):
        self.payload['proposals'][0]['value'] = 900
        result = self.run_merge(self.payload, {'s': self.blob})
        self.assertEqual(result['units']['max']['value'], 900)
        self.assertFalse(result['evidence_receipts'][0]['semantic_entailment_established'])

    def test_bad_receipts_never_enter_merge(self):
        for field, value, reason in [('sha256', '0' * 64, 'DIGEST_MISMATCH'),
                                     ('quote', '81', 'SPAN_MISMATCH'),
                                     ('start', -1, 'INVALID_RECEIPT'),
                                     ('end', True, 'INVALID_RECEIPT')]:
            with self.subTest(field=field):
                p = copy.deepcopy(self.payload)
                p['proposals'][0]['evidence'][field] = value
                result = self.run_merge(p, {'s': self.blob})
                self.assertEqual(result['units']['max']['status'], 'unsupported')
                self.assertEqual(result['evidence_receipts'][0]['reason'], reason)

    def test_missing_text_or_receipt_is_unknown(self):
        self.assertEqual(self.run_merge(self.payload, {})['evidence_receipts'][0]['reason'],
                         'SOURCE_UNAVAILABLE')
        del self.payload['proposals'][0]['evidence']
        self.assertEqual(self.run_merge(self.payload, {'s': self.blob})
                         ['evidence_receipts'][0]['reason'], 'RECEIPT_MISSING')

    def test_stale_verified_source_still_cannot_enter_current_output(self):
        self.payload['sources']['s']['current'] = False
        result = self.run_merge(self.payload, {'s': self.blob})
        self.assertEqual(result['units']['max']['status'], 'unsupported')
        self.assertEqual(len(result['stale_rejected']), 1)

    def test_order_and_duplicate_workers_do_not_change_collation(self):
        self.payload['proposals'] += [dict(self.payload['proposals'][0], worker_id='b')]
        original = copy.deepcopy(self.payload)
        for ps in itertools.permutations(self.payload['proposals']):
            candidate = dict(self.payload, proposals=list(ps))
            self.assertEqual(self.run_merge(candidate, {'s': self.blob})['units'],
                             self.run_merge(original, {'s': self.blob})['units'])
        self.assertEqual(self.payload, original)

    def test_joint_constraint_is_not_certified_by_valid_spans(self):
        self.payload['units'].append('min')
        self.payload['proposals'].append(dict(self.payload['proposals'][0], unit_id='min', value=100))
        self.payload['constraints'] = [{'left': 'min', 'op': '<=', 'right': 'max'}]
        result = self.run_merge(self.payload, {'s': self.blob})
        self.assertEqual(result['state'], 'REQUIRES_REVIEW')
        self.assertEqual(len(result['constraint_violations']), 1)

    def test_invalid_input_and_source_size_fail_closed(self):
        with self.assertRaises(MergeInputError):
            self.run_merge(self.payload, {'s': 'not bytes'})
        with self.assertRaises(MergeInputError):
            self.run_merge(self.payload, {'s': b'x' * (1024 * 1024 + 1)})
        with self.assertRaises(MergeInputError):
            self.run_merge({'proposals': []}, {})

    def test_zero_length_receipt_cannot_validate_a_missing_fact(self):
        e = self.payload['proposals'][0]['evidence']
        e.update(start=0, end=0, quote='')
        self.assertEqual(self.run_merge(self.payload, {'s': self.blob})
                         ['evidence_receipts'][0]['reason'], 'INVALID_RECEIPT')


class BaselineContract(unittest.TestCase):
    def test_union_keeps_bool_int_and_conflicts_distinct(self):
        self.assertIsNotNone(importlib.util.find_spec('unitmerge.baselines'), 'Missing comparator')
        from unitmerge.baselines import normalized_union, single_worker
        p = {'units': ['a', 'b'], 'sources': {'s': {'current': True}},
             'proposals': [{'unit_id': 'a', 'source_ref': 's', 'worker_id': 'w1', 'value': True},
                           {'unit_id': 'a', 'source_ref': 's', 'worker_id': 'w2', 'value': 1}]}
        self.assertEqual(normalized_union(p)['a']['status'], 'conflict')
        self.assertEqual(normalized_union(p)['b']['status'], 'unsupported')
        self.assertEqual(single_worker(p, 'w1')['a']['value'], True)
        self.assertEqual(single_worker(p, 'absent')['a']['status'], 'unsupported')

class ExperimentContract(unittest.TestCase):
    def test_complete_census_and_no_manufactured_advantage(self):
        import runpy
        from pathlib import Path
        result = runpy.run_path(str(Path(__file__).parents[1] / 'experiments/compare.py'))['run']()
        self.assertEqual(len(result['rows']), 21)
        metrics = ['correct_cells', 'wrong_cells', 'unresolved_cells', 'joint_violations',
                   'complete_correct_consistent_row']
        for case in {r['case'] for r in result['rows']}:
            rows = {r['arm']: r for r in result['rows'] if r['case'] == case}
            self.assertEqual([rows['checked_collation'][m] for m in metrics],
                             [rows['normalized_union'][m] for m in metrics])
        counterexample = next(r for r in result['rows']
                              if r['case'] == 'matching-quote-wrong-value'
                              and r['arm'] == 'checked_collation')
        self.assertEqual(counterexample['wrong_cells'], 1)
