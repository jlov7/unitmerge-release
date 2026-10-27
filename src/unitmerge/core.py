"""Deterministic source-aware proposal collation, NOT source-truth verification."""
from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping
from typing import Any


class MergeInputError(ValueError):
    """Invalid caller-provided merge contract."""


def _json_key(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise MergeInputError('values must be finite JSON') from exc


def _required(obj: Mapping[str, Any], key: str, expected: type) -> Any:
    value = obj.get(key)
    if type(value) is not expected or (isinstance(value, str) and not value.strip()):
        raise MergeInputError(f'{key} must be a nonempty {expected.__name__}')
    return value


def merge(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Collate proposals by known unit ID; never infer truth from agreement.

    Source registry and current flag are supplied by the caller and not authenticated
    by this method. There is no probabilistic source-weighted score.
    """
    if not isinstance(payload, dict):
        raise MergeInputError('top-level input must be an object')
    raw_units = _required(payload, 'units', list)
    if not raw_units or any(type(x) is not str or not x.strip() for x in raw_units):
        raise MergeInputError('units must contain nonempty strings')
    if len(raw_units) != len(set(raw_units)):
        raise MergeInputError('units must be unique')
    source_catalog = _required(payload, 'sources', dict)
    if any(type(k) is not str or not k or type(v) is not dict or type(v.get('current')) is not bool
           for k, v in source_catalog.items()):
        raise MergeInputError('sources entries require a boolean current field')
    proposals = _required(payload, 'proposals', list)
    by_unit: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    rejected_stale = []
    unit_set = set(raw_units)
    for index, p in enumerate(proposals):
        if not isinstance(p, dict):
            raise MergeInputError(f'proposal {index} is not an object')
        unit = _required(p, 'unit_id', str)
        source = _required(p, 'source_ref', str)
        worker = _required(p, 'worker_id', str)
        if unit not in unit_set:
            raise MergeInputError(f'proposal {index}: unknown unit {unit!r}')
        if source not in source_catalog:
            raise MergeInputError(f'proposal {index}: undeclared source {source!r}')
        if 'value' not in p:
            raise MergeInputError(f'proposal {index}: value is required (null is allowed)')
        value_key = _json_key(p['value'])
        if not source_catalog[source]['current']:
            rejected_stale.append({'unit_id':unit, 'source_ref':source})
        else:
            by_unit[unit].append((source, worker, value_key))
    outcome = {}
    residual = []
    for unit in sorted(raw_units):
        entries = by_unit[unit]
        sources_to_values: dict[str, set[str]] = defaultdict(set)
        for source, _worker, key in entries:
            sources_to_values[source].add(key)
        distinct = {k for value_set in sources_to_values.values() for k in value_set}
        cited = sorted(sources_to_values)
        # Two workers reading one source are one provenance origin, never votes.
        if not distinct:
            item = {'status':'unsupported', 'value':None, 'source_refs':[]}
        elif len(distinct) > 1:
            item = {'status':'conflict', 'value':None, 'source_refs':cited,
                    'alternatives':[{'value':json.loads(key),
                                     'source_refs':sorted(s for s, vs in sources_to_values.items() if key in vs)}
                                    for key in sorted(distinct)]}
        else:
            key = next(iter(distinct))
            item = {'status':'proposed_unverified', 'value':json.loads(key),
                    'source_refs':cited, 'independent_origins_not_established': True}
        outcome[unit] = item
        if item['status'] != 'proposed_unverified':
            residual.append(unit)
    violations = []
    constraints = payload.get('constraints', [])
    if type(constraints) is not list:
        raise MergeInputError('constraints must be a list')
    for c in constraints:
        if type(c) is not dict or set(c) != {'left', 'op', 'right'}:
            raise MergeInputError('constraint requires left/op/right')
        left, right, op = c['left'], c['right'], c['op']
        if (any(type(x) is not str for x in (left, right, op)) or
                left not in unit_set or right not in unit_set or op not in ('<=', '>=', '==')):
            raise MergeInputError('invalid constraint unit or op')
        lhs, rhs = outcome[left], outcome[right]
        if lhs['status'] != 'proposed_unverified' or rhs['status'] != 'proposed_unverified':
            continue
        a, b = lhs['value'], rhs['value']
        if op != '==' and (type(a) not in (int, float) or type(b) not in (int, float)):
            raise MergeInputError('ordered constraints require numeric values')
        ok = ((a <= b) if op == '<=' else ((a >= b) if op == '>=' else (_json_key(a) == _json_key(b))))
        if not ok:
            violations.append({'left':left, 'op':op, 'right':right})
            residual.extend((left, right))
    return {'units':outcome, 'residual':sorted(set(residual)),
            'constraint_violations':violations,
            'stale_rejected':sorted(rejected_stale, key=lambda x:(x['unit_id'],x['source_ref'])),
            'state':'REQUIRES_REVIEW' if residual else 'PROPOSALS_COLLATED',
            'claim_boundary':'agreement is not source verification or independence'}
