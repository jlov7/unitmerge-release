"""Independent simple comparators. They deliberately do not import the merger.

Pass the same structurally validated, source-eligible payload to every arm.
A worker must be selected before looking at evaluation labels.
"""
from __future__ import annotations

import json
from typing import Any


def normalized_union(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    values: dict[str, set[str]] = {unit: set() for unit in payload['units']}
    for proposal in payload['proposals']:
        if payload['sources'][proposal['source_ref']]['current']:
            values[proposal['unit_id']].add(json.dumps(
                proposal['value'], sort_keys=True, separators=(',', ':'), allow_nan=False))
    result = {}
    for unit, alternatives in sorted(values.items()):
        if not alternatives:
            result[unit] = {'status': 'unsupported', 'value': None}
        elif len(alternatives) > 1:
            result[unit] = {'status': 'conflict', 'value': None}
        else:
            result[unit] = {'status': 'proposed_unverified',
                            'value': json.loads(next(iter(alternatives)))}
    return result


def single_worker(payload: dict[str, Any], worker_id: str) -> dict[str, dict[str, Any]]:
    return normalized_union(dict(payload, proposals=[
        p for p in payload['proposals'] if p['worker_id'] == worker_id]))
