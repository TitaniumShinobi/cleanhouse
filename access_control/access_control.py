# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - config/access_control.py
#  Access control and developer-only mode
#  Devon • 2025‑01‑27
# ──────────────────────────────────────────────────────────────────────────────

import os
import logging
from typing import List, Optional
from pathlib import Path

class AccessControl:
    """
    Manages access control for CleanHouse.
    Supports developer-only mode and whitelisted email domains.
    """
    
    def __init__(self):
        self.developer_mode = self._get_developer_mode()
        self.allowed_domains = self._get_allowed_domains()
        self.whitelisted_emails = self._get_whitelisted_emails()
        self.invite_tokens = self._get_invite_tokens()
        
        logging.info(f"Access control initialized - Developer mode: {self.developer_mode}")
    
    def _get_developer_mode(self) -> bool:
        """Check if developer-only mode is enabled."""
        # Check environment variable
        env_mode = os.getenv('CLEANHOUSE_MODE', '').lower()
        if env_mode == 'developer_only':
            return True
        
        # Check for .env file
        env_file = Path('.env')
        if env_file.exists():
            try:
                with open(env_file, 'r') as f:
                    content = f.read()
                    if 'CLEANHOUSE_MODE=developer_only' in content:
                        return True
            except Exception as e:
                logging.warning(f"Could not read .env file: {e}")
        
        return False
    
    def _get_allowed_domains(self) -> List[str]:
        """Get list of allowed email domains."""
        domains = []
        
        # Check environment variable
        env_domains = os.getenv('CLEANHOUSE_ALLOWED_DOMAINS', '')
        if env_domains:
            domains.extend([d.strip() for d in env_domains.split(',')])
        
        # Check for .env file
        env_file = Path('.env')
        if env_file.exists():
            try:
                with open(env_file, 'r') as f:
                    content = f.read()
                    for line in content.split('\n'):
                        if line.startswith('CLEANHOUSE_ALLOWED_DOMAINS='):
                            domains_str = line.split('=', 1)[1].strip()
                            if domains_str:
                                domains.extend([d.strip() for d in domains_str.split(',')])
            except Exception as e:
                logging.warning(f"Could not read .env file: {e}")
        
        return domains
    
    def _get_whitelisted_emails(self) -> List[str]:
        """Get list of whitelisted email addresses."""
        emails = []
        
        # Check environment variable
        env_emails = os.getenv('CLEANHOUSE_WHITELISTED_EMAILS', '')
        if env_emails:
            emails.extend([e.strip() for e in env_emails.split(',')])
        
        # Check for .env file
        env_file = Path('.env')
        if env_file.exists():
            try:
                with open(env_file, 'r') as f:
                    content = f.read()
                    for line in content.split('\n'):
                        if line.startswith('CLEANHOUSE_WHITELISTED_EMAILS='):
                            emails_str = line.split('=', 1)[1].strip()
                            if emails_str:
                                emails.extend([e.strip() for e in emails_str.split(',')])
            except Exception as e:
                logging.warning(f"Could not read .env file: {e}")
        
        return emails
    
    def _get_invite_tokens(self) -> List[str]:
        """Get list of valid invite tokens."""
        tokens = []
        
        # Check environment variable
        env_tokens = os.getenv('CLEANHOUSE_INVITE_TOKENS', '')
        if env_tokens:
            tokens.extend([t.strip() for t in env_tokens.split(',')])
        
        # Check for .env file
        env_file = Path('.env')
        if env_file.exists():
            try:
                with open(env_file, 'r') as f:
                    content = f.read()
                    for line in content.split('\n'):
                        if line.startswith('CLEANHOUSE_INVITE_TOKENS='):
                            tokens_str = line.split('=', 1)[1].strip()
                            if tokens_str:
                                tokens.extend([t.strip() for t in tokens_str.split(',')])
            except Exception as e:
                logging.warning(f"Could not read .env file: {e}")
        
        return tokens
    
    def is_access_allowed(self, email: str, invite_token: Optional[str] = None) -> bool:
        """
        Check if access is allowed for the given email and invite token.
        
        Args:
            email: User's email address
            invite_token: Optional invite token
            
        Returns:
            bool: True if access is allowed, False otherwise
        """
        # If not in developer mode, allow all access
        if not self.developer_mode:
            return True
        
        # Check whitelisted emails first
        if email in self.whitelisted_emails:
            logging.info(f"Access allowed for whitelisted email: {email}")
            return True
        
        # Check invite token
        if invite_token and invite_token in self.invite_tokens:
            logging.info(f"Access allowed for valid invite token: {invite_token}")
            return True
        
        # Check allowed domains
        if self.allowed_domains:
            email_domain = email.split('@')[-1] if '@' in email else ''
            if email_domain in self.allowed_domains:
                logging.info(f"Access allowed for domain: {email_domain}")
                return True
        
        # Access denied
        logging.warning(f"Access denied for email: {email}")
        return False
    
    def get_access_denied_message(self) -> str:
        """Get the access denied message for users."""
        if not self.developer_mode:
            return "Access denied."
        
        message = "Access is currently restricted to developers only.\n\n"
        
        if self.allowed_domains:
            message += f"Allowed domains: {', '.join(self.allowed_domains)}\n"
        
        if self.whitelisted_emails:
            message += f"Whitelisted emails: {', '.join(self.whitelisted_emails)}\n"
        
        if self.invite_tokens:
            message += f"Invite tokens available: {len(self.invite_tokens)}\n"
        
        message += "\nPlease contact the administrator for access."
        
        return message
    
    def create_invite_token(self) -> str:
        """Create a new invite token."""
        import secrets
        import string
        
        # Generate a secure random token
        alphabet = string.ascii_letters + string.digits
        token = ''.join(secrets.choice(alphabet) for _ in range(32))
        
        # Add to tokens list
        self.invite_tokens.append(token)
        
        logging.info(f"Created new invite token: {token}")
        return token
    
    def revoke_invite_token(self, token: str) -> bool:
        """Revoke an invite token."""
        if token in self.invite_tokens:
            self.invite_tokens.remove(token)
            logging.info(f"Revoked invite token: {token}")
            return True
        return False
    
    def get_access_info(self) -> dict:
        """Get current access control information."""
        return {
            'developer_mode': self.developer_mode,
            'allowed_domains': self.allowed_domains,
            'whitelisted_emails': self.whitelisted_emails,
            'invite_tokens_count': len(self.invite_tokens),
            'total_whitelisted': len(self.whitelisted_emails) + len(self.allowed_domains)
        }

# Global access control instance
access_control = AccessControl()
