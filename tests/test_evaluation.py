"""Regression cases for the independent comparison evaluator."""
import copy
import json
import runpy
import unittest
from pathlib import Path
from unittest.mock import patch


class ComparisonEvaluationTests(unittest.TestCase):
    def evaluate(self, values, constraints):
        case = {'id': 'regression', 'text': 'Reviewed source bytes.',
                'units': list(values), 'truth': copy.deepcopy(values),
                'constraints': constraints,
                'proposals': [[unit, value, 'w1', 'source', True]
                              for unit, value in values.items()]}
        corpus = {'scope': 'Authored evaluator regression.', 'fixed_worker': 'w1',
                  'cases': [case]}
        run = runpy.run_path(str(Path(__file__).parents[1] / 'experiments/compare.py'))['run']
        # Supply a controlled corpus at the existing file-read boundary; mergers stay real.
        with patch.object(Path, 'read_bytes', return_value=json.dumps(corpus).encode()):
            return run()['rows']

    def test_unequal_values_violate_equality_in_every_arm(self):
        rows = self.evaluate({'a': 1, 'b': 2}, [{'left': 'a', 'op': '==', 'right': 'b'}])
        for row in rows:
            self.assertEqual(row['joint_violations'], 1, row['arm'])
            self.assertFalse(row['complete_correct_consistent_row'])

    def test_greater_equal_is_not_evaluated_as_less_equal(self):
        for a, b, violations in [(1, 2, 1), (2, 1, 0), (2, 2, 0)]:
            with self.subTest(a=a, b=b):
                rows = self.evaluate({'a': a, 'b': b},
                                     [{'left': 'a', 'op': '>=', 'right': 'b'}])
                for row in rows:
                    self.assertEqual(row['joint_violations'], violations, row['arm'])

    def test_less_equal_keeps_its_existing_meaning(self):
        for a, b, violations in [(1, 2, 0), (2, 1, 1), (2, 2, 0)]:
            with self.subTest(a=a, b=b):
                rows = self.evaluate({'a': a, 'b': b},
                                     [{'left': 'a', 'op': '<=', 'right': 'b'}])
                for row in rows:
                    self.assertEqual(row['joint_violations'], violations, row['arm'])

    def test_object_gold_order_does_not_change_answer_correctness(self):
        rows = self.evaluate({'answer': {'z': 1, 'a': {'y': 2, 'b': 3}}}, [])
        for row in rows:
            self.assertEqual(row['correct_cells'], 1, row['arm'])
            self.assertEqual(row['wrong_cells'], 0)
            self.assertTrue(row['complete_correct_consistent_row'])

    def test_json_boolean_and_integer_do_not_satisfy_equality(self):
        rows = self.evaluate({'a': True, 'b': 1},
                             [{'left': 'a', 'op': '==', 'right': 'b'}])
        for row in rows:
            self.assertEqual(row['joint_violations'], 1, row['arm'])

    def test_equal_objects_satisfy_equality(self):
        rows = self.evaluate({'a': {'z': 1, 'a': 2}, 'b': {'a': 2, 'z': 1}},
                             [{'left': 'a', 'op': '==', 'right': 'b'}])
        for row in rows:
            self.assertEqual(row['joint_violations'], 0, row['arm'])
            self.assertTrue(row['complete_correct_consistent_row'])
