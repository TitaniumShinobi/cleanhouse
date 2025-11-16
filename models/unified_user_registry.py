# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - models/unified_user_registry.py
#  Unified User Registry Client - Connects to Chatty's MongoDB user registry
#  Devon • 2025-01-XX
# ──────────────────────────────────────────────────────────────────────────────

import logging
import requests
import os
from typing import Optional, Dict, Any
from datetime import datetime
import hashlib
import uuid

class UnifiedUserRegistry:
    """
    Unified user registry client that connects to Chatty's MongoDB user registry.
    This ensures all applications (Chatty, VVAULT, CleanHouse) use the same user database.
    """
    
    def __init__(self, chatty_api_url: Optional[str] = None):
        """
        Initialize unified user registry client.
        
        Args:
            chatty_api_url: Base URL for Chatty API (defaults to env var or localhost)
        """
        self.chatty_api_url = chatty_api_url or os.getenv(
            'CHATTY_API_URL', 
            'http://localhost:5000'
        )
        self.logger = logging.getLogger(__name__)
    
    def create_user(
        self, 
        email: str, 
        password: str, 
        name: str,
        provider: str = "email"
    ) -> Dict[str, Any]:
        """
        Create a new user account via Chatty's unified registry.
        
        Args:
            email: User's email address
            password: Plain text password (will be hashed by Chatty)
            name: User's full name
            provider: Authentication provider (email, google, microsoft)
            
        Returns:
            dict: User data if successful, None if failed
            
        Raises:
            ValueError: If email already exists or validation fails
            ConnectionError: If cannot connect to Chatty API
        """
        try:
            response = requests.post(
                f"{self.chatty_api_url}/api/auth/signup",
                json={
                    "email": email,
                    "password": password,
                    "name": name,
                    "provider": provider
                },
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                self.logger.info(f"User created via unified registry: {email}")
                return {
                    "id": data.get("userId"),
                    "email": email,
                    "name": name,
                    "provider": provider,
                    "created_at": datetime.now().isoformat()
                }
            elif response.status_code == 400:
                error_data = response.json()
                error_msg = error_data.get("error", "User already exists")
                raise ValueError(error_msg)
            else:
                self.logger.error(f"Signup failed: {response.status_code} - {response.text}")
                raise ConnectionError(f"Failed to create user: {response.status_code}")
                
        except requests.exceptions.ConnectionError:
            self.logger.error(f"Cannot connect to Chatty API at {self.chatty_api_url}")
            raise ConnectionError(
                f"Cannot connect to Chatty API. Please ensure Chatty server is running at {self.chatty_api_url}"
            )
        except requests.exceptions.Timeout:
            self.logger.error("Chatty API request timed out")
            raise ConnectionError("Request timed out. Please try again.")
        except Exception as e:
            self.logger.error(f"Unexpected error creating user: {e}")
            raise
    
    def authenticate_user(
        self, 
        email: str, 
        password: str
    ) -> Optional[Dict[str, Any]]:
        """
        Authenticate user via Chatty's unified registry.
        Uses Python auth endpoint which handles PBKDF2 password verification.
        
        Args:
            email: User's email address
            password: Plain text password
            
        Returns:
            dict: User data if authentication successful, None otherwise
        """
        try:
            # Use Chatty's login endpoint
            response = requests.post(
                f"{self.chatty_api_url}/api/auth/login",
                json={
                    "email": email,
                    "password": password
                },
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                user_data = data.get("user", {})
                self.logger.info(f"User authenticated via unified registry: {email}")
                return {
                    "id": user_data.get("id") or user_data.get("_id") or user_data.get("sub"),
                    "email": user_data.get("email", email),
                    "name": user_data.get("name", ""),
                    "provider": user_data.get("provider", "email"),
                    "constructId": user_data.get("constructId"),
                    "vvaultPath": user_data.get("vvaultPath"),
                    "status": user_data.get("status", "active")
                }
            elif response.status_code == 401:
                self.logger.warning(f"Authentication failed for {email}: Invalid credentials")
                return None
            else:
                self.logger.warning(f"Authentication failed for {email}: {response.status_code} - {response.text}")
                return None
                
        except requests.exceptions.ConnectionError:
            self.logger.error(f"Cannot connect to Chatty API at {self.chatty_api_url}")
            return None
        except Exception as e:
            self.logger.error(f"Authentication error: {e}")
            return None
    
    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """
        Get user by email address.
        
        Args:
            email: User's email address
            
        Returns:
            dict: User data if found, None otherwise
        """
        try:
            # Use login endpoint with a dummy password to check if user exists
            # (Chatty should have a proper GET endpoint for this)
            response = requests.get(
                f"{self.chatty_api_url}/api/users/by-email/{email}",
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                return None
                
        except Exception as e:
            self.logger.error(f"Error getting user: {e}")
            return None
    
    def user_exists(self, email: str) -> bool:
        """
        Check if user exists in unified registry.
        
        Args:
            email: User's email address
            
        Returns:
            bool: True if user exists, False otherwise
        """
        user = self.get_user_by_email(email)
        return user is not None

