"""Admission for the existing CleanHouse API; no new session or token model."""
import ipaddress
import math
import time
from urllib.parse import urlsplit

from flask import g, jsonify, request, session


def _error(code, status):
    return jsonify({'success': False, 'code': code}), status


def _local_readiness_request():
    if request.method not in {'GET', 'HEAD'} or 'Authorization' in request.headers:
        return False
    if request.path == '/cleanhouse/status':
        if list(request.args.lists()) != [('ready', ['1'])]:
            return False
    elif request.path == '/cleanhouse/runtime':
        if request.query_string:
            return False
    else:
        return False
    # These are direct local launcher probes, not browser or forwarded identity.
    if request.headers.get('Origin') or request.headers.get('Referer'):
        return False
    if request.headers.get('Sec-Fetch-Site', 'none') != 'none':
        return False
    try:
        return (ipaddress.ip_address(request.remote_addr or '').is_loopback
                and urlsplit(request.host_url).hostname in {'localhost', '127.0.0.1', '::1'})
    except ValueError:
        return False


def _cookie_mutation_origin_allowed():
    from backend.api.cleanhouse import _require_allowed_origin
    origin = request.headers.get('Origin')
    if origin:
        # The legacy CORS allowlist accepts other localhost ports; cookies must not.
        return _require_allowed_origin(origin)[1] and origin == request.host_url.rstrip('/')
    return request.headers.get('Sec-Fetch-Site') == 'same-origin'


def require_cleanhouse_api_admission():
    """Called after existing auth toggles; leave stricter endpoint policy intact."""
    if request.method == 'OPTIONS':
        return None
    if _local_readiness_request():
        return None
    header = request.headers.get('Authorization')
    bearer = header is not None
    try:
        from backend.api import auth
        if bearer:
            token, error = auth._extract_bearer_token(header)
            if error:
                return _error('AUTHENTICATION_REQUIRED', 401)
            claims = auth.verify_jwt_token(token)
            if not isinstance(claims, dict):
                return _error('AUTHENTICATION_REQUIRED', 401)
            expiry = claims.get('exp')
            if isinstance(expiry, bool) or not isinstance(expiry, (int, float)) or not math.isfinite(expiry) or expiry <= time.time():
                return _error('AUTHENTICATION_REQUIRED', 401)
            user_id = claims.get('user_id')
        else:
            user_id = session.get('user_id')
            if not user_id and session.get('oauth_success') is True:
                pending = session.get('oauth_user')
                if isinstance(pending, dict):
                    user_id = pending.get('user_id')
                    if pending.get('id') not in (None, user_id):
                        return _error('AUTHENTICATION_REQUIRED', 401)
        if not isinstance(user_id, str) or not user_id.strip():
            return _error('AUTHENTICATION_REQUIRED', 401)
        user = auth.get_user_service().get_user_by_id(user_id=user_id)
        credential = claims if bearer else (session if session.get('user_id') else session.get('oauth_user', {}))
        if user is None or auth._model_user_id(user) != user_id or not auth.credential_generation_matches(user, credential):
            return _error('AUTHENTICATION_REQUIRED', 401)
    except Exception:
        # Store/validator failures must not run the protected handler.
        return _error('AUTHENTICATION_UNAVAILABLE', 503)
    if not bearer and request.method not in {'GET', 'HEAD'}:
        try:
            allowed = _cookie_mutation_origin_allowed()
        except Exception:
            return _error('AUTHENTICATION_UNAVAILABLE', 503)
        if not allowed:
            return _error('REQUEST_ORIGIN_REJECTED', 403)
    g.cleanhouse_api_user_id = user_id
    return None
