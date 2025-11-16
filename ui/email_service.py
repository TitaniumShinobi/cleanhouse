# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - email_service.py
#  Email verification service with 6-digit passcodes
#  Devon • 2025‑10‑20
# ──────────────────────────────────────────────────────────────────────────────

import smtplib
import ssl
import random
import string
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import json
import os
from pathlib import Path

class EmailVerificationService:
    """
    Handles email verification with 6-digit passcodes.
    """
    
    def __init__(self, config_file: str = "email_config.json"):
        self.config_file = Path(config_file)
        self.config = self._load_config()
        self.verification_codes = {}  # In production, use Redis or database
        
    def _load_config(self) -> Dict[str, Any]:
        """Load email configuration from file."""
        default_config = {
            "smtp_server": "smtp.gmail.com",
            "smtp_port": 587,
            "sender_email": "",
            "sender_password": "",
            "sender_name": "CleanHouse Security",
            "use_tls": True,
            "verification_code_expiry_minutes": 10,
            "max_attempts": 3
        }
        
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    return {**default_config, **config}
            except Exception as e:
                logging.error(f"Failed to load email config: {e}")
        
        # Create default config file
        self._save_config(default_config)
        return default_config
    
    def _save_config(self, config: Dict[str, Any]):
        """Save email configuration to file."""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            logging.error(f"Failed to save email config: {e}")
    
    def generate_verification_code(self) -> str:
        """Generate a 6-digit verification code."""
        return ''.join(random.choices(string.digits, k=6))
    
    def send_verification_email(self, email: str, code: str) -> bool:
        """
        Send verification email with 6-digit code.
        
        Args:
            email: Recipient email address
            code: 6-digit verification code
            
        Returns:
            True if email sent successfully, False otherwise
        """
        try:
            if not self.config.get("sender_email") or not self.config.get("sender_password"):
                logging.error("Email configuration incomplete. Please set sender_email and sender_password.")
                return False
            
            # Create message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = "CleanHouse - Email Verification"
            msg['From'] = f"{self.config['sender_name']} <{self.config['sender_email']}>"
            msg['To'] = email
            
            # Create HTML content
            html_content = self._create_verification_email_html(code)
            
            # Attach HTML content
            html_part = MIMEText(html_content, 'html')
            msg.attach(html_part)
            
            # Create plain text content
            text_content = self._create_verification_email_text(code)
            text_part = MIMEText(text_content, 'plain')
            msg.attach(text_part)
            
            # Send email
            context = ssl.create_default_context()
            
            with smtplib.SMTP(self.config['smtp_server'], self.config['smtp_port']) as server:
                if self.config.get('use_tls', True):
                    server.starttls(context=context)
                
                server.login(self.config['sender_email'], self.config['sender_password'])
                server.send_message(msg)
            
            logging.info(f"Verification email sent to {email}")
            return True
            
        except Exception as e:
            logging.error(f"Failed to send verification email to {email}: {e}")
            return False
    
    def _create_verification_email_html(self, code: str) -> str:
        """Create HTML email content."""
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>CleanHouse Email Verification</title>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: #2c3e50; color: white; padding: 20px; text-align: center; }}
                .content {{ background: #f8f9fa; padding: 30px; }}
                .code {{ background: #e74c3c; color: white; font-size: 32px; font-weight: bold; 
                        text-align: center; padding: 20px; margin: 20px 0; 
                        border-radius: 8px; letter-spacing: 5px; }}
                .footer {{ background: #ecf0f1; padding: 15px; text-align: center; font-size: 12px; color: #7f8c8d; }}
                .warning {{ background: #f39c12; color: white; padding: 15px; border-radius: 5px; margin: 15px 0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🔐 CleanHouse Security</h1>
                    <h2>Email Verification Required</h2>
                </div>
                
                <div class="content">
                    <p>Hello,</p>
                    
                    <p>You're setting up your CleanHouse account. To complete the registration, please verify your email address using the code below:</p>
                    
                    <div class="code">{code}</div>
                    
                    <div class="warning">
                        <strong>⚠️ Important:</strong>
                        <ul>
                            <li>This code expires in 10 minutes</li>
                            <li>Do not share this code with anyone</li>
                            <li>CleanHouse will never ask for this code via email</li>
                        </ul>
                    </div>
                    
                    <p>If you didn't request this verification, please ignore this email.</p>
                    
                    <p>Best regards,<br>
                    The CleanHouse Security Team</p>
                </div>
                
                <div class="footer">
                    <p>This is an automated message from CleanHouse Security System</p>
                    <p>© 2025 CleanHouse. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """
    
    def _create_verification_email_text(self, code: str) -> str:
        """Create plain text email content."""
        return f"""
CleanHouse Security - Email Verification

Hello,

You're setting up your CleanHouse account. To complete the registration, please verify your email address using the code below:

VERIFICATION CODE: {code}

IMPORTANT:
- This code expires in 10 minutes
- Do not share this code with anyone
- CleanHouse will never ask for this code via email

If you didn't request this verification, please ignore this email.

Best regards,
The CleanHouse Security Team

---
This is an automated message from CleanHouse Security System
© 2025 CleanHouse. All rights reserved.
        """
    
    def store_verification_code(self, email: str, code: str) -> bool:
        """Store verification code with expiry."""
        try:
            expiry_time = datetime.now() + timedelta(minutes=self.config['verification_code_expiry_minutes'])
            
            self.verification_codes[email] = {
                'code': code,
                'expiry': expiry_time.isoformat(),
                'attempts': 0,
                'created': datetime.now().isoformat()
            }
            
            logging.info(f"Verification code stored for {email}")
            return True
            
        except Exception as e:
            logging.error(f"Failed to store verification code for {email}: {e}")
            return False
    
    def verify_code(self, email: str, code: str) -> Dict[str, Any]:
        """
        Verify the 6-digit code.
        
        Args:
            email: User's email address
            code: 6-digit verification code
            
        Returns:
            Dict with verification result and details
        """
        try:
            if email not in self.verification_codes:
                return {
                    'valid': False,
                    'error': 'No verification code found for this email',
                    'attempts_remaining': 0
                }
            
            stored_data = self.verification_codes[email]
            
            # Check if code has expired
            expiry_time = datetime.fromisoformat(stored_data['expiry'])
            if datetime.now() > expiry_time:
                del self.verification_codes[email]
                return {
                    'valid': False,
                    'error': 'Verification code has expired',
                    'attempts_remaining': 0
                }
            
            # Check attempts
            max_attempts = self.config['max_attempts']
            if stored_data['attempts'] >= max_attempts:
                del self.verification_codes[email]
                return {
                    'valid': False,
                    'error': 'Too many failed attempts. Please request a new code.',
                    'attempts_remaining': 0
                }
            
            # Verify code
            if stored_data['code'] == code:
                # Success - remove the code
                del self.verification_codes[email]
                return {
                    'valid': True,
                    'message': 'Email verified successfully'
                }
            else:
                # Failed attempt
                stored_data['attempts'] += 1
                attempts_remaining = max_attempts - stored_data['attempts']
                
                return {
                    'valid': False,
                    'error': 'Invalid verification code',
                    'attempts_remaining': attempts_remaining
                }
                
        except Exception as e:
            logging.error(f"Error verifying code for {email}: {e}")
            return {
                'valid': False,
                'error': 'Verification failed due to system error',
                'attempts_remaining': 0
            }
    
    def send_verification_code(self, email: str) -> Dict[str, Any]:
        """
        Send a new verification code to the email.
        
        Args:
            email: User's email address
            
        Returns:
            Dict with send result and details
        """
        try:
            # Generate new code
            code = self.generate_verification_code()
            
            # Store code
            if not self.store_verification_code(email, code):
                return {
                    'success': False,
                    'error': 'Failed to store verification code'
                }
            
            # Send email
            if self.send_verification_email(email, code):
                return {
                    'success': True,
                    'message': f'Verification code sent to {email}',
                    'expiry_minutes': self.config['verification_code_expiry_minutes']
                }
            else:
                # Remove stored code if email failed
                if email in self.verification_codes:
                    del self.verification_codes[email]
                return {
                    'success': False,
                    'error': 'Failed to send verification email'
                }
                
        except Exception as e:
            logging.error(f"Error sending verification code to {email}: {e}")
            return {
                'success': False,
                'error': 'Failed to send verification code'
            }
    
    def cleanup_expired_codes(self):
        """Remove expired verification codes."""
        try:
            current_time = datetime.now()
            expired_emails = []
            
            for email, data in self.verification_codes.items():
                expiry_time = datetime.fromisoformat(data['expiry'])
                if current_time > expiry_time:
                    expired_emails.append(email)
            
            for email in expired_emails:
                del self.verification_codes[email]
            
            if expired_emails:
                logging.info(f"Cleaned up {len(expired_emails)} expired verification codes")
                
        except Exception as e:
            logging.error(f"Error cleaning up expired codes: {e}")
    
    def get_config_status(self) -> Dict[str, Any]:
        """Get email configuration status."""
        return {
            'configured': bool(self.config.get('sender_email') and self.config.get('sender_password')),
            'smtp_server': self.config.get('smtp_server', 'Not configured'),
            'sender_email': self.config.get('sender_email', 'Not configured'),
            'sender_name': self.config.get('sender_name', 'Not configured'),
            'verification_expiry_minutes': self.config.get('verification_code_expiry_minutes', 10),
            'max_attempts': self.config.get('max_attempts', 3)
        }

