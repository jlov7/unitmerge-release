"""Matched-evidence replay with labels outside the three candidate implementations."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from unitmerge.baselines import normalized_union, single_worker
from unitmerge.core import merge
from unitmerge.evidence import eligible_payload


def run() -> dict:
    raw = Path(__file__).with_name('cases.json').read_bytes()
    corpus = json.loads(raw)
    rows = []
    for case in corpus['cases']:
        blob = case['text'].encode('utf-8')
        payload = {'units': case['units'], 'sources': {'source': {
            'current': case.get('current', True)}}, 'constraints': case.get('constraints', []),
                   'proposals': []}
        for unit, value, worker, quote, valid in case['proposals']:
            start = blob.index(quote.encode())
            payload['proposals'].append({'unit_id': unit, 'value': value, 'worker_id': worker,
                                         'source_ref': 'source', 'evidence': {
                                             'sha256': hashlib.sha256(blob).hexdigest(),
                                             'start': start, 'end': start + len(quote.encode()),
                                             'quote': quote if valid else 'not the source bytes'}})
        started = time.perf_counter_ns()
        eligible, receipts = eligible_payload(payload, {'source': blob})
        eligibility_ns = time.perf_counter_ns() - started
        arms = {'checked_collation': lambda eligible=eligible: merge(eligible)['units'],
                'normalized_union': lambda eligible=eligible: normalized_union(eligible),
                'fixed_worker': lambda eligible=eligible: single_worker(eligible, corpus['fixed_worker'])}
        for name, arm in arms.items():
            started = time.perf_counter_ns()
            output = arm()
            elapsed = time.perf_counter_ns() - started
            correct = wrong = unresolved = 0
            for unit in case['units']:
                item = output[unit]
                if item['status'] != 'proposed_unverified':
                    unresolved += 1
                elif json.dumps(item['value'], sort_keys=True) == json.dumps(case['truth'][unit], sort_keys=True):
                    correct += 1
                else:
                    wrong += 1
            violations = 0
            for rule in case.get('constraints', []):
                left, right = output[rule['left']], output[rule['right']]
                if left['status'] == right['status'] == 'proposed_unverified':
                    # Independent outcome calculation, not the candidate's reported violation count.
                    a, b = left['value'], right['value']
                    if rule['op'] == '==':
                        satisfied = json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
                    elif rule['op'] == '<=':
                        satisfied = a <= b
                    else:  # merge has already validated the closed operator set.
                        satisfied = a >= b
                    violations += int(not satisfied)
            rows.append({'case': case['id'], 'arm': name, 'correct_cells': correct,
                         'wrong_cells': wrong, 'unresolved_cells': unresolved,
                         'joint_violations': violations,
                         'complete_correct_consistent_row': not (wrong or unresolved or violations),
                         'input_proposals': len(payload['proposals']),
                         'eligible_proposals': len(eligible['proposals']),
                         'receipt_failures': sum(r['status'] != 'MATCHED_BYTES' for r in receipts),
                         'shared_eligibility_ns': eligibility_ns, 'arm_ns': elapsed})
    return {'scope': corpus['scope'], 'corpus_sha256': hashlib.sha256(raw).hexdigest(),
            'baseline_note': 'Same eligible proposals for every arm; fixed worker w1, no label selection.',
            'timing_note': 'Illustrative one-run CPU timings; not a performance benchmark.', 'rows': rows}


if __name__ == '__main__':
    print(json.dumps(run(), indent=2, sort_keys=True))
