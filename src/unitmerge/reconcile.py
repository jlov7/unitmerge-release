"""Deterministic three-way JSON review. Hashes bind bytes, not semantic truth."""
from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal, InvalidOperation

MAX_INPUT_BYTES = 1024 * 1024
MAX_DEPTH = 64
MAX_NODES = 10_000
MAX_POINTER_BYTES = 4096
MAX_REVIEW_BYTES = 8 * 1024 * 1024
_MISSING = object()
_SIDES = ('base', 'left', 'right')


class SchemaSupportMissing(ValueError):
    """The caller explicitly requested the optional schema validator."""


class ReviewMismatch(ValueError):
    """Resolution inputs or options no longer reproduce the supplied review."""


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate object key')
        result[key] = value
    return result


def _constant(_value):
    raise ValueError('nonfinite number')


def _float(token):
    value = float(token)
    if not math.isfinite(value):
        raise ValueError('nonfinite number')
    try:
        if Decimal(token) != Decimal(json.dumps(value, allow_nan=False)):
            raise ValueError('lossy decimal number')
    except InvalidOperation as error:
        raise ValueError('invalid decimal number') from error
    return value


def _decode(raw, *, output=False):
    multiplier = 3 if output else 1
    if type(raw) is not bytes or len(raw) > (16 if output else 1) * MAX_INPUT_BYTES:
        raise ValueError('expected bounded UTF-8 JSON bytes')
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs,
                           parse_constant=_constant, parse_float=_float)
        pending = [(value, 0)]
        count = 0
        while pending:
            node, depth = pending.pop()
            count += 1
            if depth > MAX_DEPTH or count > multiplier * MAX_NODES:
                raise ValueError('JSON structure exceeds limits')
            if isinstance(node, float) and not math.isfinite(node):
                raise ValueError('nonfinite number')
            if isinstance(node, (dict, list)):
                pending.extend((child, depth + 1) for child in
                               (node.values() if isinstance(node, dict) else node))
        _canonical(value)  # Reject unpaired surrogates as well as nonfinite numbers.
        return value
    except (UnicodeError, RecursionError) as error:
        raise ValueError('invalid UTF-8 JSON') from error


def _same(a, b):
    if a is _MISSING or b is _MISSING:
        return a is b
    return _canonical(a) == _canonical(b)


def _slot(value):
    return {'present': False} if value is _MISSING else {'present': True, 'value': value}


def _pointer(path, key):
    pointer = path + '/' + key.replace('~', '~0').replace('/', '~1')
    if len(pointer.encode('utf-8')) > MAX_POINTER_BYTES:
        raise ValueError('JSON pointer exceeds limit')
    return pointer


def _tokens(path):
    if type(path) is not str or len(path.encode('utf-8')) > MAX_POINTER_BYTES or \
            (path and not path.startswith('/')):
        raise ValueError('invalid JSON pointer')
    for token in path.split('/')[1:]:
        if '~' in token.replace('~0', '').replace('~1', ''):
            raise ValueError('invalid JSON pointer escape')
    return [token.replace('~1', '/').replace('~0', '~') for token in path.split('/')[1:]]


def _policy(policy, values=None):
    if type(policy) is not dict or len(policy) > 64:
        raise ValueError('invalid array policy')
    for path, key in policy.items():
        tokens = _tokens(path)
        if type(key) is not str or not key or len(key.encode('utf-8')) > 256:
            raise ValueError('invalid identity key')
        if any(other != path and (not other or path.startswith(other + '/')) for other in policy):
            raise ValueError('overlapping array policy')
        if values is not None:
            found = False
            for node in values:
                for token in tokens:
                    if node is _MISSING:
                        break
                    if not isinstance(node, dict):
                        raise TypeError('policy paths must traverse objects')
                    node = node.get(token, _MISSING)
                if node is not _MISSING:
                    found = True
                    _entries(node, key)
            if not found:
                raise ValueError('array policy path absent')
    return json.loads(_canonical(policy))


def _entries(value, key):
    if not isinstance(value, list):
        raise TypeError('policy target must be an array')
    entries = {}
    for item in value:
        if type(item) is not dict or type(item.get(key)) is not str or not item[key] or \
                len(item[key].encode('utf-8')) > 256 or item[key] in entries:
            raise ValueError('array needs unique nonempty string identities')
        entries[item[key]] = item
    return entries


def _normalize(value, policy, path=''):
    if path in policy and isinstance(value, list):
        entries = _entries(value, policy[path])
        return [entries[key] for key in sorted(entries)]
    if isinstance(value, dict):
        return {key: _normalize(child, policy, _pointer(path, key))
                for key, child in value.items()}
    return value


def _schema(raw, *, check_references=False):
    schema = _decode(raw)
    draft = 'https://json-schema.org/draft/2020-12/schema'
    try:
        from jsonschema import Draft202012Validator
        from jsonschema.exceptions import SchemaError
        from referencing import Registry
        from referencing.exceptions import Unresolvable
        from referencing.jsonschema import DRAFT202012
        Draft202012Validator.check_schema(schema)
        resource = DRAFT202012.create_resource(schema)
        resolver = Registry().resolver_with_root(resource)
        resources, seen = [resource], set()
        while resources:
            resource = resources.pop()
            contents = resource.contents
            if id(contents) in seen:
                continue
            seen.add(id(contents))
            Draft202012Validator.check_schema(contents)
            if isinstance(contents, dict):
                # Interpret keywords only at schema locations. Values in const,
                # enum, default, examples and property-name maps are not schemas.
                if '$id' in contents or ('$schema' in contents and contents['$schema'] != draft):
                    raise ValueError('only a single Draft 2020-12 schema is supported')
                for keyword in ('$ref', '$dynamicRef'):
                    if keyword not in contents:
                        continue
                    reference = contents[keyword]
                    if type(reference) is not str or not reference.startswith('#'):
                        raise ValueError('only document-local references are supported')
                    if check_references:
                        try:
                            target = resolver.lookup(reference).contents
                        except TypeError as error:
                            raise ValueError('invalid schema reference') from error
                        resources.append(DRAFT202012.create_resource(target))
            resources.extend(resource.subresources())
    except ImportError as error:
        raise SchemaSupportMissing('install unitmerge[schema] to use a schema') from error
    except (SchemaError, Unresolvable) as error:
        raise ValueError('invalid local schema') from error
    return Draft202012Validator(schema, registry=Registry())


def _walk(base, left, right, path, conflicts, choices=None, policy=None, atomic=False):
    if policy and path in policy and all(isinstance(value, list) or value is _MISSING
                                        for value in (base, left, right)) and \
            left is not _MISSING and right is not _MISSING:
        maps = [{} if value is _MISSING else _entries(value, policy[path])
                for value in (base, left, right)]
        result = []
        for identity in sorted(maps[0].keys() | maps[1].keys() | maps[2].keys()):
            value = _walk(*(mapping.get(identity, _MISSING) for mapping in maps),
                          _pointer(path, identity), conflicts, choices, atomic=True)
            if value is not _MISSING:
                result.append(value)
        return result
    if _same(left, right):
        return left
    if _same(base, left):
        return right
    if _same(base, right):
        return left
    if not atomic and isinstance(left, dict) and isinstance(right, dict) and \
            (isinstance(base, dict) or base is _MISSING):
        original = {} if base is _MISSING else base
        merged = {}
        for key in sorted(original.keys() | left.keys() | right.keys()):
            pointer = _pointer(path, key)
            value = _walk(original.get(key, _MISSING), left.get(key, _MISSING),
                          right.get(key, _MISSING), pointer, conflicts, choices, policy)
            if value is not _MISSING:
                merged[key] = value
        return merged
    conflicts.append({'path': path, 'base': _slot(base), 'left': _slot(left),
                      'right': _slot(right)})
    if choices is None:
        return _MISSING
    return {'base': base, 'left': left, 'right': right}[choices[path]]


def reconcile(base: bytes, left: bytes, right: bytes, *, array_policy=None, schema=None) -> dict:
    """Return a review report for three exact JSON byte strings, without mutation.

    Object members merge recursively. Arrays are atomic. Conflicted paths are
    omitted from the incomplete automatic result and must be explicitly chosen.
    """
    raws = (base, left, right)
    values = tuple(map(_decode, raws))
    try:
        policy = _policy(array_policy, values) if array_policy is not None else {}
    except TypeError as error:
        raise ValueError('invalid array policy') from error
    if schema is not None:
        _schema(schema)
    # Normalize only explicitly keyed arrays, including unchanged/reordered ones.
    values = tuple(_normalize(value, policy) for value in values) if policy else values
    conflicts = []
    automatic = _walk(*values, '', conflicts, policy=policy)
    report = {
        'format': 'unitmerge.reconcile.v1',
        'inputs': {side: {'sha256': _digest(raw), 'bytes': len(raw)}
                   for side, raw in zip(_SIDES, raws)},
        'automatic': _slot(automatic),
        'conflicts': conflicts,
    }
    if array_policy is not None or schema is not None:
        report['format'] = 'unitmerge.reconcile.v2'
        report['options'] = {'array_policy': policy,
                             'schema_sha256': None if schema is None else _digest(schema)}
    encoded = _canonical(report)
    if len(encoded) > MAX_REVIEW_BYTES:
        raise ValueError('review exceeds byte limit')
    report['report_sha256'] = _digest(encoded)
    return report


def resolve(report: dict, decisions: dict, base: bytes, left: bytes, right: bytes, *,
            array_policy=None, schema=None) -> dict:
    """Recheck original bytes and every review field before materializing choices.

    Decisions must name each conflict exactly once and take base, left or right.
    Returned data is detached from caller objects. No custom code is evaluated.
    """
    expected = reconcile(base, left, right, array_policy=array_policy, schema=schema)
    if _canonical(report) != _canonical(expected):
        raise ReviewMismatch('stale or modified review')
    if type(decisions) is not dict or set(decisions) != {'report_sha256', 'decisions'} or \
            decisions['report_sha256'] != expected['report_sha256'] or \
            type(decisions['decisions']) is not list:
        raise ValueError('invalid decisions')
    required = {conflict['path'] for conflict in expected['conflicts']}
    if len(decisions['decisions']) != len(required):
        raise ValueError('every conflict needs exactly one decision')
    choices = {}
    for decision in decisions['decisions']:
        if type(decision) is not dict or set(decision) != {'path', 'take'} or \
                type(decision['path']) is not str or decision['path'] not in required or \
                decision['path'] in choices or type(decision['take']) is not str or \
                decision['take'] not in _SIDES:
            raise ValueError('invalid conflict decision')
        choices[decision['path']] = decision['take']
    policy = {} if array_policy is None else array_policy
    values = tuple(map(_decode, (base, left, right)))
    if policy:
        values = tuple(_normalize(value, policy) for value in values)
    merged = _walk(*values, '', [], choices, policy)
    if schema is not None:
        from referencing.exceptions import Unresolvable
        try:
            if not _schema(schema, check_references=True).is_valid(merged):
                raise ValueError('candidate fails local schema')
        except (Unresolvable, RecursionError) as error:
            raise ValueError('invalid schema reference') from error
    result = {
        'merged': merged,
        'receipt': {
            'format': 'unitmerge.resolution.v1',
            'report_sha256': expected['report_sha256'],
            'inputs': expected['inputs'],
            'decisions': [{'path': path, 'take': choices[path]} for path in sorted(choices)],
            'merged_content_sha256': _digest(_canonical(merged)),
            'semantic_correctness_established': False,
        },
    }
    if 'options' in expected:
        result['receipt']['format'] = 'unitmerge.resolution.v2'
        result['receipt']['options'] = expected['options']
    return result


def _hash(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _inputs(value):
    if type(value) is not dict or set(value) != set(_SIDES):
        raise ValueError('invalid input identities')
    for identity in value.values():
        if type(identity) is not dict or set(identity) != {'sha256', 'bytes'} or \
                not _hash(identity['sha256']) or type(identity['bytes']) is not int or \
                not 0 <= identity['bytes'] <= MAX_INPUT_BYTES:
            raise ValueError('invalid input identity')


def _options(value):
    if type(value) is not dict or set(value) != {'array_policy', 'schema_sha256'} or \
            (value['schema_sha256'] is not None and not _hash(value['schema_sha256'])):
        raise ValueError('invalid options identity')
    _policy(value['array_policy'])


def _validate_report(report):
    if type(report) is not dict:
        raise ValueError('invalid review')
    version = report.get('format')
    keys = {'format', 'inputs', 'automatic', 'conflicts', 'report_sha256'}
    if version == 'unitmerge.reconcile.v2':
        keys.add('options')
        _options(report.get('options'))
    elif version != 'unitmerge.reconcile.v1':
        raise ValueError('invalid review version')
    if set(report) != keys or type(report['conflicts']) is not list:
        raise ValueError('invalid review fields')
    _inputs(report['inputs'])
    def slot(value):
        if type(value) is not dict or type(value.get('present')) is not bool or \
                set(value) != ({'present', 'value'} if value['present'] else {'present'}):
            raise ValueError('invalid review slot')
    slot(report['automatic'])
    paths = set()
    for conflict in report['conflicts']:
        if type(conflict) is not dict or set(conflict) != {'path', *_SIDES}:
            raise ValueError('invalid conflict')
        _tokens(conflict['path'])
        if conflict['path'] in paths:
            raise ValueError('duplicate conflict path')
        paths.add(conflict['path'])
        for side in _SIDES:
            slot(conflict[side])
    content = _canonical({key: value for key, value in report.items() if key != 'report_sha256'})
    if len(content) > MAX_REVIEW_BYTES or report['report_sha256'] != _digest(content):
        raise ValueError('modified review')


def decisions_template(report: dict) -> dict:
    """Create bound, deliberately unresolved choices without deciding anything."""
    _validate_report(report)
    return {'report_sha256': report['report_sha256'],
            'decisions': [{'path': c['path'], 'take': 'UNRESOLVED'} for c in report['conflicts']]}


def render_review(report: dict) -> str:
    """Render local alternatives as inert text. Values are deliberately disclosed."""
    _validate_report(report)
    lines = ['Review ' + report['report_sha256'],
             'Alternatives disclose configuration values. No decisions are made.']
    for conflict in report['conflicts']:
        lines.append('Path: ' + (json.dumps(conflict['path'], ensure_ascii=True)
                                 if conflict['path'] else '(root)'))
        for side in _SIDES:
            value = conflict[side]
            lines.append('  ' + side + ': ' + (json.dumps(value['value'], ensure_ascii=True,
                          sort_keys=True, allow_nan=False) if value['present'] else 'MISSING'))
    if not report['conflicts']:
        lines.append('No conflicts.')
    return '\n'.join(lines) + '\n'


def verify_output(output: bytes, receipt: dict) -> dict:
    """Compare a strict own-format receipt with bytes/content, without authentication."""
    if type(receipt) is not dict:
        raise ValueError('invalid receipt')
    keys = {'format', 'report_sha256', 'inputs', 'decisions', 'merged_content_sha256',
            'semantic_correctness_established', 'output_bytes_sha256'}
    if receipt.get('format') == 'unitmerge.resolution.v2':
        keys.add('options')
        _options(receipt.get('options'))
    elif receipt.get('format') != 'unitmerge.resolution.v1':
        raise ValueError('invalid receipt version')
    if set(receipt) != keys or receipt['semantic_correctness_established'] is not False or \
            any(not _hash(receipt[key]) for key in
                ('report_sha256', 'merged_content_sha256', 'output_bytes_sha256')) or \
            type(receipt['decisions']) is not list:
        raise ValueError('invalid receipt fields')
    _inputs(receipt['inputs'])
    paths = []
    for choice in receipt['decisions']:
        if type(choice) is not dict or set(choice) != {'path', 'take'} or \
                choice['take'] not in _SIDES:
            raise ValueError('invalid receipt decision')
        _tokens(choice['path'])
        paths.append(choice['path'])
    if paths != sorted(set(paths)):
        raise ValueError('invalid receipt decision order')
    value = _decode(output, output=True)
    content_match = _digest(_canonical(value)) == receipt['merged_content_sha256']
    bytes_match = _digest(output) == receipt['output_bytes_sha256']
    return {'status': 'MATCH' if content_match and bytes_match else
                     'BYTES_DIFFER' if content_match else 'CONTENT_DIFFER',
            'bytes_match': bytes_match, 'content_match': content_match,
            'authenticated': False}
