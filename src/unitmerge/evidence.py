"""Recheck caller-supplied source bytes; matching bytes are NOT semantic entailment."""
from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from typing import Any

from .core import MergeInputError, merge

MAX_SOURCE_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 8 * MAX_SOURCE_BYTES
MAX_PROPOSALS = 10000


def eligible_payload(payload: dict[str, Any], texts: dict[str, bytes]) -> tuple[dict, list[dict]]:
    """Return eligible proposals and a complete receipt for every input proposal.

    Offsets are half-open UTF-8 BYTE offsets, not Unicode character offsets.
    The caller owns the registry/current flags; no source authenticity is inferred.
    This function never reads paths, fetches URLs, interprets instructions or executes code.
    """
    if type(payload) is not dict or type(payload.get('proposals')) is not list:
        raise MergeInputError('payload requires a proposals list')
    if len(payload['proposals']) > MAX_PROPOSALS:
        raise MergeInputError('too many proposals')
    if (type(texts) is not dict or len(texts) > 256 or
            any(type(k) is not str or type(v) is not bytes or len(v) > MAX_SOURCE_BYTES
                for k, v in texts.items())):
        raise MergeInputError('sources must be bounded byte strings')
    if sum(map(len, texts.values())) > MAX_TOTAL_BYTES:
        raise MergeInputError('source collection exceeds byte limit')
    # Validate the original structural contract before filtering, so malformed
    # proposals cannot disappear silently merely because their receipt failed.
    merge(payload)
    hashes = {key: hashlib.sha256(value).hexdigest() for key, value in texts.items()}
    accepted, receipts = [], []
    for index, proposal in enumerate(payload['proposals']):
        source = proposal['source_ref']
        evidence = proposal.get('evidence')
        reason = None
        if source not in texts:
            reason = 'SOURCE_UNAVAILABLE'
        elif evidence is None:
            reason = 'RECEIPT_MISSING'
        elif (type(evidence) is not dict or set(evidence) != {'sha256', 'start', 'end', 'quote'} or
              type(evidence['start']) is not int or type(evidence['end']) is not int or
              type(evidence['quote']) is not str or not evidence['quote'] or
              type(evidence['sha256']) is not str or
              re.fullmatch(r'[0-9a-f]{64}', evidence['sha256']) is None or
              not 0 <= evidence['start'] < evidence['end'] <= len(texts[source])):
            reason = 'INVALID_RECEIPT'
        elif hashes[source] != evidence['sha256']:
            reason = 'DIGEST_MISMATCH'
        else:
            try:
                quote = evidence['quote'].encode('utf-8')
                actual = texts[source][evidence['start']:evidence['end']]
                actual.decode('utf-8')  # Reject a span cutting through a code point.
                if actual != quote:
                    reason = 'SPAN_MISMATCH'
            except UnicodeError:
                reason = 'SPAN_MISMATCH'
        receipts.append({'proposal_index': index, 'source_ref': source,
                         'status': 'MATCHED_BYTES' if reason is None else 'UNVERIFIED',
                         'reason': reason, 'semantic_entailment_established': False})
        if reason is None:
            accepted.append(deepcopy(proposal))
    filtered = deepcopy(payload)
    filtered['proposals'] = accepted
    return filtered, receipts


def checked_merge(payload: dict[str, Any], texts: dict[str, bytes]) -> dict[str, Any]:
    """Collate only byte-matched proposals, preserving all rejected receipts."""
    filtered, receipts = eligible_payload(payload, texts)
    result = merge(filtered)
    result['evidence_receipts'] = receipts
    result['evidence_boundary'] = 'Byte identity only; not authenticity, truth or independent support.'
    return result
