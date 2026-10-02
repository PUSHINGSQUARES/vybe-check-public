"""Requested anonymous advisory decisions with explicit, bounded consent.

Real route quotes remain unavailable until complete primary billing bounds
are established. Neither a key nor an operator-supplied price proves a bound.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
import unicodedata
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from .privacy import clean
from .install import no_links
from .workshop import _SafeLock, _open_regular, _read_regular

ENDPOINTS = {'typesafe': 'https://api.typesafe.ai/v1/systemone',
             'openrouter': 'https://openrouter.ai/api/alpha/decisions'}
MODELS = {'typesafe': 'jev-1.13.0', 'openrouter': 'typesafe/jev-1.13'}
# Explicit documented resolution of the requested OpenRouter alias.
ACTUAL_MODELS = {'typesafe': frozenset({'jev-1.13.0'}),
                 'openrouter': frozenset({'typesafe/jev-1.13-20260917'})}
PICK_INSTRUCTIONS = 'Select the candidate that best satisfies the anonymous constraints.'
RELEVANCE_INSTRUCTIONS = 'Rate how relevant the proposed addition is to the anonymous constraints.'
CONTRADICTION_INSTRUCTIONS = 'Rate whether the proposed addition contradicts the anonymous constraints.'
MAX_REQUEST_BYTES = 24576
MAX_RESPONSE_BYTES = 128000
PROBABILITY_SUM_TOLERANCE = 1e-9
QUOTE_TTL_SECONDS = 300
_UNSAFE = re.compile(r'[A-Za-z][A-Za-z0-9+.-]*://|\b(?:data|blob):|\bwww\.|'
                     r'\b[^\s@]+@[^\s@]+\.[^\s@]+|(?<!\w)/[^\s]+|'
                     r'[A-Za-z0-9+/=_-]{64,}|(?:[A-Za-z0-9+/]{24,}\s+)+[A-Za-z0-9+/]{24,}={0,2}|'
                     r'\b(?:base64|binary\s+blob)\b', re.I)


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate decision field')
        result[key] = value
    return result


def read_object(path):
    """Bounded local operator input; duplicate keys are never silently replaced."""
    failed = False
    try:
        value = json.loads(_read_regular(Path(path), MAX_RESPONSE_BYTES), object_pairs_hook=_unique)
        if not isinstance(value, dict):
            failed = True
    except Exception:
        failed = True
    if failed:
        raise ValueError('Decision input file unavailable')
    return value


def _safe_text(value, deny_tokens=()):
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_REQUEST_BYTES:
        raise ValueError('Anonymous decision input required')
    text = unicodedata.normalize('NFKC', value)
    if any(unicodedata.category(ch) in ('Cc', 'Cf') and ch not in '\n\t' for ch in text):
        raise ValueError('Anonymous decision input required')
    if _UNSAFE.search(text) or clean(text) != text:
        raise ValueError('Anonymous decision input required')
    if any(token in text.casefold() for token in deny_tokens):
        raise ValueError('Anonymous decision input required')
    return value


def _labels(criteria, minimum):
    if (not isinstance(criteria, dict) or not minimum <= len(criteria) <= 8 or
            any(not isinstance(k, str) or re.fullmatch('option_[1-8]', k) is None for k in criteria)):
        raise ValueError('Anonymous decision input required')


@dataclass(frozen=True)
class PreparedRequest:
    route: str
    model: str
    source_image_version: int
    body: bytes

    @property
    def questions(self):
        wire = json.loads(self.body)['questions']
        return {name: {key: value for key, value in item.items() if key != 'instructions'}
                for name, item in wire.items()}


def prepare_request(anonymous, route, *, deny_tokens=()):
    """Use only a caller-supplied anonymous object, never workshop contents.

    The caller must supply local identity deny tokens and inspect the exact
    outgoing text. Pattern checks cannot discover every identity or encoding.
    Deny tokens are transient; they never become payload or receipt fields.
    """
    failed = False
    try:
        if not isinstance(route, str) or route not in MODELS:
            raise ValueError()
        if not isinstance(deny_tokens, (list, tuple)) or any(
                not isinstance(t, str) or not t.strip() for t in deny_tokens):
            raise ValueError()
        tokens = tuple(unicodedata.normalize('NFKC', t).casefold() for t in deny_tokens)
        if not isinstance(anonymous, dict) or set(anonymous) != {
                'constraints', 'options', 'purpose', 'source_image_version'}:
            raise ValueError()
        version = anonymous['source_image_version']
        if isinstance(version, bool) or not isinstance(version, int) or not 1 <= version <= 2147483647:
            raise ValueError()
        purpose = anonymous['purpose']
        if purpose not in ('addition', 'model'):
            raise ValueError()
        constraints = anonymous['constraints']
        if not isinstance(constraints, list) or not 1 <= len(constraints) <= 64:
            raise ValueError()
        for value in constraints:
            _safe_text(value, tokens)
        options = anonymous['options']
        _labels(options, 2 if purpose == 'model' else 1)
        if purpose == 'addition' and set(options) != {'option_1'}:
            raise ValueError()
        for value in options.values():
            _safe_text(value, tokens)
        state = _json_bytes(anonymous).decode('utf-8')
        questions = ({'pick': {'type': 'choice', 'instructions': PICK_INSTRUCTIONS, 'criteria': options}}
                     if purpose == 'model' else {
                         'relevance': {'type': 'noul', 'instructions': RELEVANCE_INSTRUCTIONS},
                         'contradiction': {'type': 'noul', 'instructions': CONTRADICTION_INSTRUCTIONS}})
        body = _json_bytes({'model': MODELS[route], 'state': state, 'questions': questions})
        if (len(body) > MAX_REQUEST_BYTES or any(
                token in unicodedata.normalize('NFKC', body.decode('utf-8')).casefold() for token in tokens)):
            raise ValueError()
    except (ValueError, TypeError, OverflowError, UnicodeError):
        failed = True
    if failed:
        raise ValueError('Anonymous decision input required')
    return PreparedRequest(route, MODELS[route], version, body)


def _checked(request):
    failed = False
    try:
        if not isinstance(request, PreparedRequest) or not isinstance(request.body, bytes):
            raise ValueError()
        if len(request.body) > MAX_REQUEST_BYTES:
            raise ValueError()
        wire = json.loads(request.body, object_pairs_hook=_unique)
        rebuilt = prepare_request(json.loads(wire['state'], object_pairs_hook=_unique), request.route)
        if rebuilt != request:
            raise ValueError()
    except (ValueError, TypeError, KeyError, UnicodeError):
        failed = True
    if failed:
        raise ValueError('Anonymous decision input required')
    return request


def probability(value):
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or
            not 0 <= value <= 1 or not math.isfinite(value)):
        raise ValueError('Invalid decision probability')
    return float(value)


def validate_answers(answers, questions):
    if not isinstance(questions, dict) or not questions or not isinstance(answers, dict) or set(answers) != set(questions):
        raise ValueError('Invalid decision question IDs')
    result = {}
    for name, question in questions.items():
        answer = answers[name]
        if (not isinstance(question, dict) or not isinstance(answer, dict) or
                answer.get('type') != question.get('type')):
            raise ValueError('Invalid decision type')
        if question.get('type') == 'noul':
            result[name] = {'type': 'noul', 'noul': probability(answer.get('noul'))}
        elif question.get('type') == 'choice':
            criteria = question.get('criteria')
            _labels(criteria, 2)
            choice = answer.get('choice')
            if not isinstance(choice, str) or choice not in criteria:
                raise ValueError('Unknown decision choice')
            probabilities = answer.get('probabilities')
            if not isinstance(probabilities, dict) or set(probabilities) != set(criteria):
                raise ValueError('Invalid probability choices')
            values = {k: probability(probabilities[k]) for k in criteria}
            if not math.isclose(math.fsum(values.values()), 1, rel_tol=0, abs_tol=PROBABILITY_SUM_TOLERANCE):
                raise ValueError('Invalid probability sum')
            if values[choice] != max(values.values()):
                raise ValueError('Selected decision is not a maximum')
            result[name] = {'type': 'choice', 'choice': choice,
                            'confidence': probability(answer.get('confidence')), 'probabilities': values}
        else:
            raise ValueError('Unsupported decision type')
    return result


def validate_response(value, request):
    _checked(request)
    if (not isinstance(value, dict) or not isinstance(value.get('model'), str) or
            value['model'] not in ACTUAL_MODELS[request.route]):
        raise ValueError('Invalid actual decision model')
    return validate_answers(value.get('answers'), request.questions)


def validate_advice(payload, session):
    """Transport-free allowlist for the existing record_advice event."""
    invalid = 'Advice validation is unavailable: invalid advice record'
    if not isinstance(payload, dict) or set(payload) != {
            'source_image_version', 'route', 'model', 'payload_sha256', 'questions', 'answers'}:
        raise ValueError(invalid)
    version = payload['source_image_version']
    if (isinstance(version, bool) or not isinstance(version, int) or
            version not in {x['version'] for x in session['image_versions']}):
        raise ValueError('Unknown advice source')
    route = payload['route']
    if not isinstance(route, str) or route not in MODELS or payload['model'] != MODELS[route]:
        raise ValueError(invalid)
    if not isinstance(payload['payload_sha256'], str) or re.fullmatch('[a-f0-9]{64}', payload['payload_sha256']) is None:
        raise ValueError('Invalid advice payload hash')
    questions = payload['questions']
    if not isinstance(questions, dict) or set(questions) not in ({'pick'}, {'relevance', 'contradiction'}):
        raise ValueError('Invalid advice question IDs')
    for name, question in questions.items():
        if name == 'pick':
            if not isinstance(question, dict) or set(question) != {'type', 'criteria'} or question['type'] != 'choice':
                raise ValueError('Invalid choice question')
            _labels(question['criteria'], 2)
            for value in question['criteria'].values():
                _safe_text(value)
        elif question != {'type': 'noul'}:
            raise ValueError('Invalid Noul question')
    return {'source_image_version': version, 'route': route, 'model': MODELS[route],
            'payload_sha256': payload['payload_sha256'], 'answers': validate_answers(payload['answers'], questions),
            'status': 'advisory'}


@dataclass(frozen=True)
class BillingBounds:
    """Complete trusted billing ceiling, including all overhead and fees.

    Only internal primary evidence may supply this value. There is no CLI or
    user JSON override. Context capacity is not a billable token ceiling.
    """
    pricing_url: str
    pricing_date: str
    valid_until: int
    max_input_tokens: int
    max_output_tokens: int
    input_usd_per_million: Decimal
    output_usd_per_million: Decimal
    request_fees_usd: Decimal


def _primary_bounds(route):
    # No complete primary bound is established for either pinned route.
    return None


def _money(value):
    if not isinstance(value, (str, Decimal)):
        raise ValueError('Invalid spend bound')
    try:
        result = Decimal(value)
        if not result.is_finite() or result < 0 or result > Decimal('1000000'):
            raise ValueError('Invalid spend bound')
    except InvalidOperation:
        raise ValueError('Invalid spend bound') from None
    return result


def _bound_fields(request, now):
    bound = _primary_bounds(request.route)
    if not isinstance(bound, BillingBounds):
        return None
    try:
        if (not isinstance(now, int) or isinstance(now, bool) or
                not isinstance(bound.valid_until, int) or isinstance(bound.valid_until, bool) or
                bound.valid_until <= now or not isinstance(bound.pricing_url, str) or
                not bound.pricing_url.startswith('https://') or
                date.fromisoformat(bound.pricing_date) > date.fromtimestamp(now)):
            return None
        for count in (bound.max_input_tokens, bound.max_output_tokens):
            if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 1000000000:
                return None
        input_rate = _money(bound.input_usd_per_million)
        output_rate = _money(bound.output_usd_per_million)
        fees = _money(bound.request_fees_usd)
        total = (bound.max_input_tokens * input_rate + bound.max_output_tokens * output_rate) / Decimal('1000000') + fees
        return {'route': request.route, 'model': request.model, 'payload_sha256': hashlib.sha256(request.body).hexdigest(),
                'source_image_version': request.source_image_version, 'pricing_url': bound.pricing_url,
                'pricing_date': bound.pricing_date, 'max_input_tokens': bound.max_input_tokens,
                'max_output_tokens': bound.max_output_tokens, 'input_usd_per_million': str(input_rate),
                'output_usd_per_million': str(output_rate), 'request_fees_usd': str(fees),
                'total_upper_bound_usd': str(total), 'call_limit': 1}
    except (ValueError, TypeError, OverflowError):
        return None


def quote(request, *, now=None):
    _checked(request)
    now = int(time.time()) if now is None else now
    fields = _bound_fields(request, now)
    if fields is None:
        return {'status': 'unavailable', 'reason': 'billing_unbounded'}
    receipt = {**fields, 'receipt_id': uuid4().hex,
               'expires_at': min(now + QUOTE_TTL_SECONDS, _primary_bounds(request.route).valid_until)}
    receipt['receipt_sha256'] = hashlib.sha256(_json_bytes(receipt)).hexdigest()
    return receipt


def verify_consent(request, receipt, approval, *, now=None):
    """Recalculate trusted bounds, never accept arbitrary receipt prices."""
    _checked(request)
    now = int(time.time()) if now is None else now
    fields = _bound_fields(request, now)
    if fields is None:
        return 'billing_unbounded'
    try:
        expected = set(fields) | {'receipt_id', 'receipt_sha256', 'expires_at'}
        if not isinstance(receipt, dict) or set(receipt) != expected:
            return 'invalid_quote'
        if any(type(receipt[k]) is not type(v) or receipt[k] != v for k, v in fields.items()):
            return 'invalid_quote'
        if (not isinstance(receipt['receipt_id'], str) or re.fullmatch('[a-f0-9]{32}', receipt['receipt_id']) is None or
                type(receipt['expires_at']) is not int or not now < receipt['expires_at'] <= now + QUOTE_TTL_SECONDS or
                receipt['expires_at'] > _primary_bounds(request.route).valid_until):
            return 'expired_quote'
        without_hash = {k: v for k, v in receipt.items() if k != 'receipt_sha256'}
        if receipt['receipt_sha256'] != hashlib.sha256(_json_bytes(without_hash)).hexdigest():
            return 'invalid_quote'
        if not isinstance(approval, dict) or set(approval) != expected | {'approved', 'max_usd'}:
            return 'approval_required'
        if approval['approved'] is not True or any(type(approval[k]) is not type(receipt[k]) or approval[k] != receipt[k] for k in expected):
            return 'approval_mismatch'
        if _money(approval['max_usd']) < _money(fields['total_upper_bound_usd']):
            return 'ceiling_too_low'
    except (ValueError, TypeError, OverflowError):
        return 'invalid_approval'
    return None


class _ReservationLock(_SafeLock):
    def _get_fh(self):
        path = Path(self.filename)
        for attempt in range(2):
            no_links(path)
            try:
                return super()._get_fh()
            except FileNotFoundError as exc:
                # Only the observed anchored leaf open may retry once. Parent
                # and descriptor checks still fail closed, without a retry.
                if attempt or exc.filename != '.reservation.lock':
                    raise
        raise OSError('Local reservation unavailable')


def _reserve(receipt):
    # Per-user, not per-session: the same approval cannot send from two roots.
    folder = no_links(Path.home() / '.vybe-check-security' / 'judge-attempts')
    folder.mkdir(parents=True, mode=0o700, exist_ok=True)
    marker = folder / (receipt['receipt_id'] + '.attempt')
    with _ReservationLock(str(folder / '.reservation.lock'), mode='a', timeout=5):
        fd = _open_regular(marker, create=True)
        with os.fdopen(fd, 'ab') as stream:
            if os.fstat(stream.fileno()).st_size:
                return False
            stream.write(_json_bytes({'receipt_sha256': receipt['receipt_sha256'], 'status': 'spent'}) + b'\n')
            stream.flush()
            os.fsync(stream.fileno())
    return True


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class TransportUnavailable(RuntimeError):
    def __init__(self, reason='transport_unavailable'):
        self.reason = reason
        super().__init__('Decision transport unavailable')


def send_once(endpoint, key, body):
    """One pinned TLS request, no redirect, no retry, bounded read."""
    if (endpoint not in ENDPOINTS.values() or not isinstance(key, str) or not key or
            not isinstance(body, bytes) or len(body) > MAX_REQUEST_BYTES or key.encode('utf-8') in body):
        raise ValueError('Invalid decision payload')
    invalid = False
    try:
        route = next(name for name, url in ENDPOINTS.items() if url == endpoint)
        wire = json.loads(body, object_pairs_hook=_unique)
        anonymous = json.loads(wire['state'], object_pairs_hook=_unique)
        prepared = PreparedRequest(route, MODELS[route], anonymous['source_image_version'], body)
        _checked(prepared)
    except Exception:
        invalid = True
    if invalid:
        raise ValueError('Invalid decision payload')
    failed = None
    try:
        request = Request(endpoint, data=body, method='POST', headers={
            'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
        with build_opener(NoRedirect()).open(request, timeout=5) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            failed = 'response_too_large'
        else:
            value = json.loads(raw, object_pairs_hook=_unique)
    except TimeoutError:
        failed = 'transport_timeout'
    except URLError as exc:
        failed = 'transport_timeout' if isinstance(exc.reason, TimeoutError) else 'transport_unavailable'
    except Exception:
        failed = 'transport_unavailable'
    # Raise outside handlers: untrusted content cannot remain in the chain.
    if failed:
        raise TransportUnavailable(failed)
    return value


def run_advice(request, receipt, approval, store, session_id, revision, *,
               credentials=None, transport=None, now=None):
    """Reserve before selected-account key access; any attempt is consumed."""
    reason = None
    try:
        reason = verify_consent(request, receipt, approval, now=now)
    except Exception:
        reason = 'invalid_input'
    if reason:
        return {'status': 'unavailable', 'reason': reason}
    try:
        session = store.read(session_id)
        if (type(revision) is not int or session['revision'] != revision or
                session['selected_image_version'] != request.source_image_version):
            return {'status': 'unavailable', 'reason': 'stale_source'}
        if not _reserve(receipt):
            return {'status': 'unavailable', 'reason': 'attempt_spent'}
    except Exception:
        return {'status': 'unavailable', 'reason': 'local_state_unavailable'}
    failure = None
    try:
        if credentials is None:
            from .credentials import Credentials
            credentials = Credentials()
        key = credentials.read(request.route)
        if not isinstance(key, str) or not key.strip():
            failure = 'credential_unavailable'
        elif key.encode('utf-8') in request.body:
            failure = 'credential_in_payload'
        else:
            # Recheck revision after reservation and key loading, before send.
            latest = store.read(session_id)
            if latest['revision'] != revision or latest['selected_image_version'] != request.source_image_version:
                failure = 'stale_source'
            else:
                try:
                    response = (transport or send_once)(ENDPOINTS[request.route], key, request.body)
                except TimeoutError:
                    failure = 'transport_timeout'
                except TransportUnavailable as exc:
                    failure = exc.reason if exc.reason in {'transport_timeout', 'response_too_large'} else 'transport_unavailable'
                except Exception:
                    failure = 'transport_unavailable'
                if failure is None:
                    try:
                        answers = validate_response(response, request)
                    except Exception:
                        failure = 'invalid_response'
                    if failure is None:
                        weak = (answers['pick']['confidence'] < .5 if 'pick' in answers else
                                answers['relevance']['noul'] < .5 or answers['contradiction']['noul'] >= .5)
                        if weak:
                            return {'status': 'weak', 'reason': 'low_decision_strength'}
                        payload = {'source_image_version': request.source_image_version, 'route': request.route,
                                   'model': request.model, 'payload_sha256': receipt['payload_sha256'],
                                   'questions': request.questions, 'answers': answers}
                        try:
                            store.apply(session_id, revision, 'record_advice', payload)
                        except Exception:
                            failure = 'local_state_unavailable'
                        if failure is None:
                            return {'status': 'advisory', 'source_image_version': request.source_image_version,
                                    'answers': answers}
    except Exception:
        failure = 'credential_unavailable'
    return {'status': 'unavailable', 'reason': failure or 'transport_unavailable'}
