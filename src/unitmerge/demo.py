"""Synthetic first-use cases, including a valid receipt for a false value."""
import hashlib
from copy import deepcopy

from .baselines import normalized_union
from .evidence import checked_merge, eligible_payload


def run() -> dict:
    text = 'Température: 80 °C'.encode()
    start = text.index(b'80')
    packet = {'units': ['max'], 'sources': {'s': {'current': True}}, 'proposals': [
        {'unit_id': 'max', 'source_ref': 's', 'worker_id': 'w1', 'value': 80,
         'evidence': {'sha256': hashlib.sha256(text).hexdigest(),
                      'start': start, 'end': start + 2, 'quote': '80'}}]}
    inputs = {name: deepcopy(packet) for name in ('matched', 'bad_digest', 'conflict', 'false_value')}
    inputs['bad_digest']['proposals'][0]['evidence']['sha256'] = '0' * 64
    inputs['conflict']['proposals'].append(dict(deepcopy(packet['proposals'][0]),
                                               worker_id='w2', value=81))
    inputs['false_value']['proposals'][0]['value'] = 900
    cases = {}
    for name, payload in inputs.items():
        checked = checked_merge(payload, {'s': text})
        eligible, _ = eligible_payload(payload, {'s': text})
        union = normalized_union(eligible)
        same = all(all(checked['units'][u][key] == union[u][key] for key in ('status', 'value'))
                   for u in payload['units'])
        cases[name] = {'checked': checked, 'normalized_union': union, 'same_as_union': same}
    return {'provenance': 'AUTHORED_SYNTHETIC', 'cases': cases,
            'boundary': 'Matching bytes do not establish that a proposed value follows from the quote.',
            'comparison': 'No advantage over normalized union is established.'}
