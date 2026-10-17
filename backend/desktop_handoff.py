"""Ephemeral single-process desktop OAuth handoffs; restart safely requires retry."""
import hashlib
import secrets
import threading
import time
from urllib.parse import urlsplit
from flask import request, session, jsonify, redirect

TTL = 300
LIMIT = 128
_lock = threading.RLock()
_pending = {}


def _prune():
    now = time.time()
    for key in list(_pending):
        if _pending[key]['expires'] <= now:
            del _pending[key]


def _error(code, status=400):
    return jsonify(success=False, code=code), status


def _origin_allowed():
    return request.headers.get('Origin') == request.host_url.rstrip('/')


def cancel_session():
    with _lock:
        _pending.pop(session.pop('desktop_transaction', None), None)


def start(identifier):
    with _lock:
        _prune()
        record = _pending.get(identifier)
        if not record or record['state'] != 'pending':
            return _error('HANDOFF_EXPIRED_OR_USED')
        from backend.api.auth import _oauth_redirect_uri
        callback = urlsplit(_oauth_redirect_uri(record['provider']))
        canonical = f'{callback.scheme}://{callback.netloc}'
        if canonical != request.host_url.rstrip('/'):
            return redirect(canonical + '/api/auth/desktop/start/' + identifier)
        record['state'] = 'browser_started'
        session['desktop_browser_transaction'] = identifier
        return redirect('/api/auth/oauth/' + record['provider'])


def take_start(provider):
    identifier = session.pop('desktop_browser_transaction', None)
    if not identifier:
        return None
    with _lock:
        _prune()
        record = _pending.get(identifier)
        if not record or record['provider'] != provider or record['state'] != 'browser_started':
            raise ValueError('Invalid desktop handoff')
        return {'desktop_transaction': identifier, 'signup_proof': record.get('signup_proof')}


def finish(identifier, user=None, report=None):
    with _lock:
        _prune()
        record = _pending.get(identifier)
        if not record or record['state'] != 'browser_started':
            return False
        record.update(state='complete' if user else 'denied', user=user, report=report)
        return True


def install(bp):
    @bp.route('/auth/desktop/prepare', methods=['POST'])
    def desktop_prepare():
        if not _origin_allowed():
            return _error('HANDOFF_ORIGIN_REJECTED', 403)
        from backend.api import auth
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or data.get('provider') not in auth._ALLOWED_OAUTH_PROVIDERS:
            return _error('HANDOFF_PROVIDER_REQUIRED')
        runtime = auth.auth_runtime_config.provider_config(data['provider'])
        if not runtime.get('enabled') or not runtime.get('available'):
            return _error('PROVIDER_UNAVAILABLE', 409)
        proof = None
        if data.get('intent') == 'signup':
            # Shared signup validator is supplied by the independently scoped signup repair.
            validator = getattr(auth, '_validate_signup_intent', None)
            if validator is None:
                return _error('SIGNUP_VALIDATION_UNAVAILABLE', 503)
            proof, error = validator(data)
            if error is not None:
                return error
        elif data.get('intent', 'signin') != 'signin':
            return _error('HANDOFF_INTENT_INVALID')
        with _lock:
            _prune()
            cancel_session()
            if len(_pending) >= LIMIT:
                return _error('HANDOFF_CAPACITY', 503)
            identifier, verifier, initiator = (secrets.token_urlsafe(32) for _ in range(3))
            _pending[identifier] = dict(provider=data['provider'], proof=hashlib.sha256(verifier.encode()).digest(),
                                        initiator=initiator, expires=time.time()+TTL, state='pending', signup_proof=proof)
            session['desktop_transaction'] = identifier
            session['desktop_initiator'] = initiator
            response = jsonify(success=True, transactionId=identifier, verifier=verifier, expiresIn=TTL)
            response.headers['Cache-Control'] = 'no-store'
            return response

    @bp.route('/auth/desktop/start/<identifier>', methods=['GET'])
    def desktop_start(identifier):
        return start(identifier)

    @bp.route('/auth/desktop/redeem', methods=['POST'])
    def desktop_redeem():
        if not _origin_allowed():
            return _error('HANDOFF_ORIGIN_REJECTED', 403)
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return _error('HANDOFF_INVALID')
        identifier, verifier = data.get('transactionId'), data.get('verifier')
        if not isinstance(identifier, str) or not isinstance(verifier, str):
            return _error('HANDOFF_INVALID')
        with _lock:
            _prune()
            record = _pending.get(identifier)
            if (not record or session.get('desktop_transaction') != identifier or
                    session.get('desktop_initiator') != record['initiator'] or
                    not secrets.compare_digest(hashlib.sha256(verifier.encode()).digest(), record['proof'])):
                return _error('HANDOFF_INVALID', 401)
            if record['state'] in ('pending', 'browser_started'):
                return jsonify(success=False, code='HANDOFF_PENDING'), 202
            del _pending[identifier]
            session.pop('desktop_transaction', None)
            session.pop('desktop_initiator', None)
            if record['state'] != 'complete':
                return _error('HANDOFF_DENIED', 403)
            # Reuse the existing OAuth session-completion path, including future session policy.
            session['oauth_user'] = record['user']
            session['oauth_success'] = True
            session['oauth_login_report'] = record['report']
            from backend.api.auth import oauth_user
            return oauth_user()

    @bp.route('/auth/desktop/cancel', methods=['POST'])
    def desktop_cancel():
        if not _origin_allowed():
            return _error('HANDOFF_ORIGIN_REJECTED', 403)
        cancel_session()
        return jsonify(success=True)
