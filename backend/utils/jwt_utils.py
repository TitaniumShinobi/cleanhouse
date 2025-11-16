"""
JWT Token Utilities for CleanHouse Authentication
"""

import jwt
import secrets
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any
import logging

# JWT configuration
JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY')
JWT_ALGORITHM = 'HS256'
JWT_EXPIRATION_HOURS = 24 * 7  # 7 days

# Generate and store secret key if not set
if not JWT_SECRET_KEY:
    secret_key_file = Path.home() / '.cleanhouse' / '.jwt_secret_key'
    if secret_key_file.exists():
        JWT_SECRET_KEY = secret_key_file.read_text().strip()
    else:
        JWT_SECRET_KEY = secrets.token_hex(32)
        secret_key_file.parent.mkdir(parents=True, exist_ok=True)
        secret_key_file.write_text(JWT_SECRET_KEY)
        logging.info("Generated new JWT secret key")

def generate_jwt_token(user_data: Dict[str, Any]) -> str:
    """
    Generate JWT token for authenticated user.
    
    Args:
        user_data: Dictionary containing user information (user_id, email, full_name, role)
        
    Returns:
        str: JWT token
    """
    payload = {
        'user_id': user_data.get('user_id'),
        'email': user_data.get('email'),
        'full_name': user_data.get('full_name', ''),
        'role': user_data.get('role', 'user'),
        'iat': datetime.utcnow(),  # Issued at
        'exp': datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS)  # Expiration
    }
    
    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return token

def verify_jwt_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verify and decode JWT token.
    
    Args:
        token: JWT token string
        
    Returns:
        dict: Decoded payload if valid, None if invalid
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logging.warning("JWT token expired")
        return None
    except jwt.InvalidTokenError as e:
        logging.warning(f"Invalid JWT token: {e}")
        return None

def get_user_from_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Get user data from JWT token.
    
    Args:
        token: JWT token string
        
    Returns:
        dict: User data if token is valid, None otherwise
    """
    payload = verify_jwt_token(token)
    if payload:
        return {
            'user_id': payload.get('user_id'),
            'email': payload.get('email'),
            'full_name': payload.get('full_name', ''),
            'role': payload.get('role', 'user')
        }
    return None

def refresh_jwt_token(token: str) -> Optional[str]:
    """
    Refresh JWT token if it's close to expiring.
    
    Args:
        token: Current JWT token
        
    Returns:
        str: New JWT token if refresh successful, None otherwise
    """
    payload = verify_jwt_token(token)
    if not payload:
        return None
    
    # Check if token expires within 24 hours
    exp_time = datetime.utcfromtimestamp(payload.get('exp', 0))
    time_until_expiry = exp_time - datetime.utcnow()
    
    if time_until_expiry.total_seconds() < 24 * 3600:  # Less than 24 hours
        # Generate new token with same user data
        user_data = {
            'user_id': payload.get('user_id'),
            'email': payload.get('email'),
            'full_name': payload.get('full_name', ''),
            'role': payload.get('role', 'user')
        }
        return generate_jwt_token(user_data)
    
    return token  # Token still valid, return original

