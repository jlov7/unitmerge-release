import copy
import json
import unittest
from pathlib import Path

from unitmerge.core import MergeInputError, merge

ROOT = Path(__file__).parents[1]


def data():
    return json.loads((ROOT/'examples/product_packet.json').read_text())


class MergeTests(unittest.TestCase):
    def test_example_collates_with_stale_record_kept(self):
        r=merge(data())
        self.assertEqual(r['units']['part-17.width_mm']['value'],200)
        self.assertEqual(r['state'],'PROPOSALS_COLLATED')
        self.assertEqual(len(r['stale_rejected']),1)

    def test_permutation_invariant(self):
        x=data(); expected=merge(x)
        for order in [list(reversed(x['proposals'])), x['proposals'][::2]+x['proposals'][1::2]]:
            y=copy.deepcopy(x);y['proposals']=order
            self.assertEqual(merge(y),expected)

    def test_duplicate_workers_do_not_create_independent_origin(self):
        x=data();x['proposals'].append(dict(x['proposals'][0],worker_id='duplicate'))
        r=merge(x)
        self.assertEqual(r['units']['part-17.width_mm']['source_refs'],['spec-A-v3'])

    def test_conflict_not_broken_by_majority(self):
        x=data();x['sources']['s3']={'current':True};x['proposals'] += [
            {'unit_id':'part-17.width_mm','value':201,'source_ref':'s3','worker_id':'w3'},
            {'unit_id':'part-17.width_mm','value':200,'source_ref':'spec-A-v3','worker_id':'w4'}]
        r=merge(x)
        self.assertEqual(r['units']['part-17.width_mm']['status'],'conflict')
        self.assertIn('part-17.width_mm',r['residual'])

    def test_same_source_conflicting_observations_remain_conflict(self):
        x=data();x['proposals'].append(dict(x['proposals'][0],value=201))
        self.assertEqual(merge(x)['units']['part-17.width_mm']['status'],'conflict')

    def test_rejected_stale_cannot_override_current(self):
        x=data();self.assertEqual(merge(x)['units']['part-17.width_mm']['value'],200)

    def test_stale_only_is_unsupported(self):
        x=data();x['sources']['spec-A-v3']['current']=False
        self.assertEqual(merge(x)['units']['part-17.width_mm']['status'],'unsupported')

    def test_missing_unit_is_residual(self):
        x=data();x['units'].append('part-17.unknown')
        self.assertIn('part-17.unknown',merge(x)['residual'])

    def test_constraint_violation_requires_review(self):
        x=data();x['proposals'][2]['value']=-30
        r=merge(x)
        self.assertEqual(r['state'],'REQUIRES_REVIEW')
        self.assertEqual(len(r['constraint_violations']),1)

    def test_equal_constraint_distinguishes_bool_from_one(self):
        x=data();x['constraints']=[{'left':'part-17.compatible','op':'==','right':'part-17.width_mm'}]
        self.assertTrue(merge(x)['constraint_violations'])

    def test_json_keys_different_types_do_not_silently_merge(self):
        x=data();x['proposals'].append(dict(x['proposals'][0],value='200'))
        self.assertEqual(merge(x)['units']['part-17.width_mm']['status'],'conflict')

    def test_valid_null_is_not_missing(self):
        x=data();x['proposals'][0]['value']=None
        self.assertEqual(merge(x)['units']['part-17.width_mm']['status'],'proposed_unverified')
        self.assertIsNone(merge(x)['units']['part-17.width_mm']['value'])

    def test_unregistered_source_rejected(self):
        x=data();x['proposals'][0]['source_ref']='fake'
        with self.assertRaises(MergeInputError):merge(x)

    def test_unknown_unit_rejected(self):
        x=data();x['proposals'][0]['unit_id']='made-up'
        with self.assertRaises(MergeInputError):merge(x)

    def test_nan_rejected(self):
        x=data();x['proposals'][0]['value']=float('nan')
        with self.assertRaises(MergeInputError):merge(x)

    def test_extra_source_dict_without_boolean_current_rejected(self):
        x=data();x['sources']['x']={'current':'yes'}
        with self.assertRaises(MergeInputError):merge(x)

    def test_duplicate_unit_definition_rejected(self):
        x=data();x['units'].append(x['units'][0])
        with self.assertRaises(MergeInputError):merge(x)

    def test_bad_constraint_op_rejected(self):
        x=data();x['constraints'][0]['op']='eval'
        with self.assertRaises(MergeInputError):merge(x)

    def test_constraint_fields_reject_non_strings_without_tracebacks(self):
        for field in ('left', 'right', 'op'):
            for value in ([], {}, None, True, 1, 1.0):
                with self.subTest(field=field, value=value):
                    x = data()
                    x['constraints'][0][field] = value
                    with self.assertRaises(MergeInputError):
                        merge(x)

    def test_candidate_truth_not_claimed(self):
        self.assertEqual(merge(data())['claim_boundary'], 'agreement is not source verification or independence')


if __name__=='__main__':unittest.main()
