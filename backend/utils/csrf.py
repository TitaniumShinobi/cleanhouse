"""
CSRF Protection Utilities for CleanHouse
"""

import secrets
from flask import session, request, abort, jsonify
from functools import wraps
import logging

def generate_csrf_token():
    """
    Generate CSRF token and store in session.
    
    Returns:
        str: CSRF token
    """
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(16)
    return session['csrf_token']

def validate_csrf_token(token: str) -> bool:
    """
    Validate CSRF token.
    
    Args:
        token: CSRF token to validate
        
    Returns:
        bool: True if token is valid, False otherwise
    """
    if 'csrf_token' not in session:
        return False
    return secrets.compare_digest(session['csrf_token'], token)

def csrf_protect():
    """
    Decorator to protect routes with CSRF validation.
    
    Usage:
        @bp.route('/endpoint', methods=['POST'])
        @csrf_protect()
        def endpoint():
            ...
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if request.method in ['POST', 'PUT', 'DELETE', 'PATCH']:
                # Try to get token from header first, then form data
                token = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token')
                
                if not token:
                    logging.warning("CSRF token missing")
                    abort(403, description='CSRF token missing')
                
                if not validate_csrf_token(token):
                    logging.warning("CSRF token validation failed")
                    abort(403, description='CSRF token validation failed')
            
            return f(*args, **kwargs)
        return wrapper
    return decorator

def csrf_exempt(f):
    """
    Decorator to exempt a route from CSRF protection.
    
    Usage:
        @bp.route('/endpoint', methods=['POST'])
        @csrf_exempt
        def endpoint():
            ...
    """
    f.csrf_exempt = True
    return f

