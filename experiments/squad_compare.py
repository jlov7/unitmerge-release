"""Independent-label numeric extraction pilot. No network or model calls."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import string
import sys
from collections import Counter
from pathlib import Path

from unitmerge.baselines import normalized_union, single_worker
from unitmerge.core import merge
from unitmerge.evidence import eligible_payload

PROTOCOL_BYTES = Path(__file__).with_name('squad-protocol-v1.json').read_bytes()
PROTOCOL = json.loads(PROTOCOL_BYTES)
PREFIXES = tuple(PROTOCOL['selection']['question_prefixes'])
STOP_WORDS = set(PROTOCOL['extractors']['stop_words'])
NUMBER = re.compile(r'(?<!\w)\d+(?:,\d{3})*(?:\.\d+)?(?!\w)')


def select_inputs(corpus: dict, count: int = 32) -> list[dict]:
    """Select only from public input fields, never answerability or gold answers."""
    if type(count) is not int or not 1 <= count <= 32:
        raise ValueError('case count must be an integer from 1 to 32')
    if type(corpus) is not dict or corpus.get('version') != 'v2.0':
        raise ValueError('SQuAD v2.0 required')
    articles = corpus.get('data')
    if type(articles) is not list:
        raise ValueError('dataset articles must be a list')
    selected, seen = [], set()
    for article in articles:
        if type(article) is not dict or type(article.get('title')) is not str:
            raise ValueError('article title required')
        paragraphs = article.get('paragraphs')
        if type(paragraphs) is not list:
            raise ValueError('paragraph list required')
        for paragraph in paragraphs:
            if type(paragraph) is not dict or type(paragraph.get('context')) is not str:
                raise ValueError('context text required')
            context = paragraph['context']
            if len(context.encode('utf-8')) > 1024 * 1024:
                raise ValueError('source exceeds evidence byte limit')
            questions = paragraph.get('qas')
            if type(questions) is not list:
                raise ValueError('question list required')
            for qa in questions:
                if (type(qa) is not dict or type(qa.get('id')) is not str or not qa['id']
                        or type(qa.get('question')) is not str or not qa['question']):
                    raise ValueError('question identity and text required')
                if qa['id'] in seen:
                    raise ValueError('duplicate question identity')
                seen.add(qa['id'])
                if len(selected) < count and qa['question'].strip().lower().startswith(PREFIXES):
                    selected.append({'id': qa['id'], 'title': article['title'],
                                     'question': qa['question'], 'context': context})
    if len(selected) != count:
        raise ValueError('not enough input-selected cases; no replacement rule')
    return selected


def worker_proposals(question: str, context: str, source_id: str) -> list[dict]:
    """Two frozen source-only rules. Neither receives benchmark labels."""
    numbers = list(NUMBER.finditer(context))
    if not numbers:
        return []
    terms = set(re.findall(r'[a-z]{3,}', question.lower())) - STOP_WORDS
    sentences = []
    for sentence in re.finditer(r'[^.!?]+(?:[.!?]|$)', context):
        found = NUMBER.search(sentence.group())
        if found is not None:
            overlap = len(terms & set(re.findall(r'[a-z]{3,}', sentence.group().lower())))
            sentences.append((overlap, sentence.start() + found.start(),
                              sentence.start() + found.end()))
    # A decimal may be split by sentence punctuation; preserve the complete numeric token.
    best_start = max(sentences, key=lambda value: value[0])[1]
    best = next(number for number in numbers if number.start() <= best_start < number.end())
    blob = context.encode('utf-8')
    digest = hashlib.sha256(blob).hexdigest()
    proposals = []
    for worker, number in [('w1', numbers[0]), ('w2', best)]:
        value = number.group()
        start = len(context[:number.start()].encode('utf-8'))
        proposals.append({'unit_id': 'answer', 'value': value, 'worker_id': worker,
                          'source_ref': source_id, 'evidence': {
                              'sha256': digest, 'start': start,
                              'end': start + len(value.encode('utf-8')), 'quote': value}})
    return proposals


def _normalize(text: str) -> list[str]:
    text = text.lower().translate(str.maketrans('', '', string.punctuation))
    return re.sub(r'\b(a|an|the)\b', ' ', text).split()


def score_answer(prediction: str, answers: list[str]) -> dict:
    predicted = _normalize(prediction)
    exact = 0
    best_f1 = 0.0
    for answer in answers or ['']:
        gold = _normalize(answer)
        exact = max(exact, int(predicted == gold))
        if not predicted or not gold:
            f1 = float(predicted == gold)
        else:
            overlap = sum((Counter(predicted) & Counter(gold)).values())
            f1 = 2 * overlap / (len(predicted) + len(gold))
        best_f1 = max(best_f1, f1)
    return {'exact_match': exact, 'f1': best_f1}


def _gold_answers(qa: dict, context: str) -> list[str]:
    impossible, answers = qa.get('is_impossible'), qa.get('answers')
    if type(impossible) is not bool or type(answers) is not list:
        raise ValueError('explicit benchmark answerability and answers required')
    if impossible != (len(answers) == 0):
        raise ValueError('answerability disagrees with answer list')
    for answer in answers:
        if type(answer) is not dict:
            raise ValueError('answer record required')
        start, text = answer.get('answer_start'), answer.get('text')
        if (type(start) is not int or start < 0 or type(text) is not str or not text
                or context[start:start + len(text)] != text):
            raise ValueError('gold character span does not match selected source')
    return [answer['text'] for answer in answers]


def run_pilot(corpus: dict, count: int = 32) -> dict:
    inputs = select_inputs(corpus, count)
    labels = {qa['id']: qa for article in corpus['data']
              for paragraph in article['paragraphs'] for qa in paragraph['qas']}
    rows = []
    for item in inputs:
        answers = _gold_answers(labels[item['id']], item['context'])
        blob = item['context'].encode('utf-8')
        payload = {'units': ['answer'], 'sources': {item['id']: {'current': True}},
                   'proposals': worker_proposals(item['question'], item['context'], item['id'])}
        eligible, receipts = eligible_payload(payload, {item['id']: blob})
        arms = {'checked_collation': merge(eligible)['units'],
                'normalized_union': normalized_union(eligible),
                'fixed_worker_w1': single_worker(eligible, 'w1')}
        for arm, units in arms.items():
            output = units['answer']
            prediction = output['value'] if output['status'] == 'proposed_unverified' else ''
            rows.append({'case_id': item['id'], 'arm': arm, 'status': output['status'],
                         'answerable': bool(answers), **score_answer(prediction, answers),
                         'prediction_sha256': hashlib.sha256(prediction.encode()).hexdigest(),
                         'source_sha256': hashlib.sha256(blob).hexdigest(),
                         'eligible_proposals': len(eligible['proposals']),
                         'receipt_failures': sum(r['status'] != 'MATCHED_BYTES' for r in receipts)})
    summary = []
    for arm in PROTOCOL['arms']:
        group = [row for row in rows if row['arm'] == arm]
        summary.append({'arm': arm, 'cases': len(group),
                        'answerable_cases': sum(row['answerable'] for row in group),
                        'unanswerable_cases': sum(not row['answerable'] for row in group),
                        'exact_match': sum(row['exact_match'] for row in group) / len(group),
                        'f1': sum(row['f1'] for row in group) / len(group),
                        'answerable_proposed': sum(row['answerable'] and
                            row['status'] == 'proposed_unverified' for row in group),
                        'unanswerable_false_answers': sum(not row['answerable'] and
                            row['status'] == 'proposed_unverified' for row in group),
                        'status_counts': dict(Counter(row['status'] for row in group))})
    pairs = {}
    for row in rows:
        if row['arm'] in ('checked_collation', 'normalized_union'):
            parity = {key: row[key] for key in ['status', 'exact_match', 'f1', 'prediction_sha256']}
            previous = pairs.setdefault(row['case_id'], parity)
            if previous != parity:
                raise ValueError('candidate/union parity failed; investigate before interpreting')
    return {'scope': PROTOCOL['purpose'], 'protocol_sha256': hashlib.sha256(PROTOCOL_BYTES).hexdigest(),
            'selected_ids': [item['id'] for item in inputs], 'rows': rows, 'summary': summary,
            'candidate_union_parity': True, 'limitations': PROTOCOL['ceilings']}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, required=True,
                        help='Already acquired pinned SQuAD development JSON. No download occurs.')
    args = parser.parse_args()
    try:
        if args.corpus.stat().st_size > 8 * 1024 * 1024:
            raise ValueError('corpus exceeds 8 MiB limit')
        raw = args.corpus.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != PROTOCOL['dataset_sha256']:
            raise ValueError('corpus differs from the frozen data hash')
        result = run_pilot(json.loads(raw.decode('utf-8')))
        result['dataset_sha256'] = digest
        sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + '\n')
        return 0
    except (OSError, ValueError, UnicodeError, RecursionError):
        sys.stderr.write(json.dumps({'status': 'FAIL', 'event': 'squad_pilot',
                                     'reason': 'Pinned corpus or evaluation contract rejected.'}) + '\n')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
