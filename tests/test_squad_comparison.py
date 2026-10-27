"""Authored regressions for the external-label pilot; no corpus is bundled."""
import copy
import hashlib
import runpy
import unittest
from pathlib import Path


def corpus(context, questions):
    return {'version': 'v2.0', 'data': [{'title': 'Authored tests', 'paragraphs': [
        {'context': context, 'qas': questions}]}]}


def question(identifier, text='How many people?', answers=None):
    answers = [] if answers is None else answers
    return {'id': identifier, 'question': text, 'answers': answers,
            'is_impossible': not bool(answers)}


class SquadComparisonTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).parents[1] / 'experiments/squad_compare.py'
        self.assertTrue(path.is_file(), 'Missing independent-label comparison runner')
        self.api = runpy.run_path(str(path))

    def test_selection_is_input_only_even_when_gold_changes(self):
        data = corpus('Population 10.', [question('q1', answers=[{'text': '10', 'answer_start': 11}])])
        selected = self.api['select_inputs'](data, 1)
        changed = copy.deepcopy(data)
        changed['data'][0]['paragraphs'][0]['qas'][0].update(
            answers=[{'text': 'wrong hidden answer', 'answer_start': 999}], is_impossible=True)
        self.assertEqual(selected, self.api['select_inputs'](changed, 1))
        self.assertEqual(set(selected[0]), {'id', 'title', 'question', 'context'})
        self.assertNotIn('answers', selected[0])

    def test_selection_keeps_original_order_and_question_prefixes(self):
        data = corpus('10 20.', [question('skip', 'Who was here?'), question('first'),
                                 question('second', 'In what year did this happen?'), question('third')])
        self.assertEqual([x['id'] for x in self.api['select_inputs'](data, 2)],
                         ['first', 'second'])

    def test_not_enough_cases_and_duplicate_ids_fail(self):
        data = corpus('10.', [question('q1')])
        with self.assertRaises(ValueError):
            self.api['select_inputs'](data, 2)
        data['data'][0]['paragraphs'][0]['qas'].append(question('q1'))
        with self.assertRaises(ValueError):
            self.api['select_inputs'](data, 2)

    def test_workers_produce_utf8_byte_spans_and_source_digests(self):
        text = 'Température 20 degrees. The population is 60.'
        proposals = self.api['worker_proposals']('How many population residents?', text, 's')
        self.assertEqual([(p['worker_id'], p['value']) for p in proposals], [('w1', '20'), ('w2', '60')])
        blob = text.encode()
        for p in proposals:
            receipt = p['evidence']
            self.assertEqual(blob[receipt['start']:receipt['end']].decode(), p['value'])
            self.assertEqual(receipt['sha256'], hashlib.sha256(blob).hexdigest())
            self.assertEqual(receipt['quote'], p['value'])

    def test_no_numbers_produces_no_proposal(self):
        self.assertEqual(self.api['worker_proposals']('How many?', 'No number is given.', 's'), [])

    def test_alternative_gold_answers_and_token_f1(self):
        self.assertEqual(self.api['score_answer']('The twenty', ['twenty', '20']),
                         {'exact_match': 1, 'f1': 1.0})
        score = self.api['score_answer']('42', ['42 43'])
        self.assertEqual(score['exact_match'], 0)
        self.assertAlmostEqual(score['f1'], 2 / 3)

    def test_unanswerable_labels_require_empty_prediction(self):
        self.assertEqual(self.api['score_answer']('', []), {'exact_match': 1, 'f1': 1.0})
        self.assertEqual(self.api['score_answer']('10', []), {'exact_match': 0, 'f1': 0.0})

    def test_all_arms_and_unanswerable_false_answers_remain_in_denominator(self):
        data = corpus('Population 10.', [
            question('answerable', answers=[{'text': '10', 'answer_start': 11}]),
            question('unanswerable')])
        result = self.api['run_pilot'](data, 2)
        self.assertEqual(len(result['rows']), 6)
        self.assertEqual(len(result['summary']), 3)
        for arm in result['summary']:
            self.assertEqual(arm['cases'], 2)
            self.assertEqual(arm['answerable_cases'], 1)
            self.assertEqual(arm['unanswerable_cases'], 1)
            self.assertEqual(arm['unanswerable_false_answers'], 1)
            self.assertEqual(arm['exact_match'], 0.5)

    def test_conflicts_are_retained_and_not_called_intentional_abstentions(self):
        data = corpus('Temperature 10 degrees. The population is 20.', [
            question('q1', 'How many population residents?',
                     [{'text': '20', 'answer_start': 42}])])
        result = self.api['run_pilot'](data, 1)
        rows = {x['arm']: x for x in result['rows']}
        for name in ['checked_collation', 'normalized_union']:
            self.assertEqual(rows[name]['status'], 'conflict')
            self.assertEqual(rows[name]['exact_match'], 0)
        self.assertEqual(rows['fixed_worker_w1']['status'], 'proposed_unverified')

    def test_gold_span_must_match_selected_source(self):
        data = corpus('Population 10.', [question('q1', answers=[{'text': '11', 'answer_start': 11}])])
        with self.assertRaises(ValueError):
            self.api['run_pilot'](data, 1)

    def test_unknown_corpus_version_and_boolean_case_count_fail(self):
        data = corpus('10.', [question('q1')])
        with self.assertRaises(ValueError):
            self.api['select_inputs'](data, True)
        data['version'] = 'unsupported'
        with self.assertRaises(ValueError):
            self.api['select_inputs'](data, 1)
