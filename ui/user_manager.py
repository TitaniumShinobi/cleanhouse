# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - user_manager.py
#  User authentication and data management
#  Devon • 2025‑10‑20
# ──────────────────────────────────────────────────────────────────────────────

import os
import sqlite3
import hashlib
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

class UserManager:
    """
    Handles user authentication, data isolation, and role-based access control.
    """
    
    def __init__(self, base_dir: str = None):
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.db_path = self.base_dir / "user_auth.db"
        self.userdata_dir = self.base_dir / "userdata"
        self.current_user = None
        
        # Create directories
        self.userdata_dir.mkdir(exist_ok=True)
        
        # Initialize database
        self._init_database()
    
    def _init_database(self):
        """Initialize the SQLite database for user authentication."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Create users table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        email TEXT UNIQUE NOT NULL,
                        password_hash TEXT NOT NULL,
                        role TEXT DEFAULT 'user',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_login TIMESTAMP,
                        preferences TEXT DEFAULT '{}'
                    )
                """)
                
                # Create sessions table for "remember me" functionality
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        token TEXT UNIQUE NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        expires_at TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users (id)
                    )
                """)
                
                conn.commit()
                logging.info("User database initialized successfully")
                
        except Exception as e:
            logging.error(f"Failed to initialize user database: {e}")
            raise
    
    def _hash_password(self, password: str) -> str:
        """Hash a password using SHA-256 with salt."""
        salt = "cleanhouse_salt_2025"
        return hashlib.sha256((password + salt).encode()).hexdigest()
    
    def create_user(self, email: str, password: str, role: str = "user") -> bool:
        """
        Create a new user account.
        
        Args:
            email: User's email address
            password: Plain text password
            role: User role ('user' or 'dev')
            
        Returns:
            True if user created successfully, False otherwise
        """
        try:
            password_hash = self._hash_password(password)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Check if user already exists
                cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
                if cursor.fetchone():
                    logging.warning(f"User {email} already exists")
                    return False
                
                # Create user
                cursor.execute("""
                    INSERT INTO users (email, password_hash, role)
                    VALUES (?, ?, ?)
                """, (email, password_hash, role))
                
                user_id = cursor.lastrowid
                conn.commit()
                
                # Create user data directory
                user_dir = self.userdata_dir / email.replace("@", "_at_").replace(".", "_")
                user_dir.mkdir(exist_ok=True)
                
                # Create subdirectories
                (user_dir / "scan_results").mkdir(exist_ok=True)
                (user_dir / "logs").mkdir(exist_ok=True)
                (user_dir / "preferences").mkdir(exist_ok=True)
                
                # Create default preferences
                default_prefs = {
                    "theme": "default",
                    "scan_interval": 300,
                    "notifications": True,
                    "auto_scan": False
                }
                
                with open(user_dir / "preferences" / "settings.json", "w") as f:
                    json.dump(default_prefs, f, indent=2)
                
                logging.info(f"User {email} created successfully with role {role}")
                return True
                
        except Exception as e:
            logging.error(f"Failed to create user {email}: {e}")
            return False
    
    def authenticate_user(self, email: str, password: str) -> Optional[Dict[str, Any]]:
        """
        Authenticate a user with email and password.
        
        Args:
            email: User's email address
            password: Plain text password
            
        Returns:
            User dictionary if authentication successful, None otherwise
        """
        try:
            password_hash = self._hash_password(password)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT id, email, role, preferences
                    FROM users 
                    WHERE email = ? AND password_hash = ?
                """, (email, password_hash))
                
                result = cursor.fetchone()
                
                if result:
                    user_id, email, role, preferences = result
                    
                    # Update last login
                    cursor.execute("""
                        UPDATE users 
                        SET last_login = CURRENT_TIMESTAMP 
                        WHERE id = ?
                    """, (user_id,))
                    conn.commit()
                    
                    user_data = {
                        "id": user_id,
                        "email": email,
                        "role": role,
                        "preferences": json.loads(preferences) if preferences else {},
                        "user_dir": self.userdata_dir / email.replace("@", "_at_").replace(".", "_")
                    }
                    
                    self.current_user = user_data
                    logging.info(f"User {email} authenticated successfully")
                    return user_data
                else:
                    logging.warning(f"Authentication failed for {email}")
                    return None
                    
        except Exception as e:
            logging.error(f"Authentication error for {email}: {e}")
            return None
    
    def get_current_user(self) -> Optional[Dict[str, Any]]:
        """Get the currently authenticated user."""
        return self.current_user
    
    def logout(self):
        """Log out the current user."""
        self.current_user = None
        logging.info("User logged out")
    
    def update_user_preferences(self, preferences: Dict[str, Any]) -> bool:
        """Update user preferences."""
        if not self.current_user:
            return False
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    UPDATE users 
                    SET preferences = ? 
                    WHERE id = ?
                """, (json.dumps(preferences), self.current_user["id"]))
                
                conn.commit()
                
                # Update current user data
                self.current_user["preferences"] = preferences
                
                # Save to user directory
                user_prefs_file = self.current_user["user_dir"] / "preferences" / "settings.json"
                with open(user_prefs_file, "w") as f:
                    json.dump(preferences, f, indent=2)
                
                logging.info("User preferences updated successfully")
                return True
                
        except Exception as e:
            logging.error(f"Failed to update user preferences: {e}")
            return False
    
    def has_role(self, required_role: str) -> bool:
        """Check if current user has the required role."""
        if not self.current_user:
            return False
        
        # Developer role has access to everything
        if self.current_user["role"] == "dev":
            return True
        
        # Check specific role
        return self.current_user["role"] == required_role
    
    def can_access_module(self, module_name: str) -> bool:
        """Check if current user can access a specific module."""
        if not self.current_user:
            return False
        
        # Define module access rules
        module_rules = {
            "zaelith": ["dev"],
            "lie_detection": ["dev"],
            "advanced_monitoring": ["dev"],
            "admin_tools": ["dev"],
            "basic_scan": ["user", "dev"],
            "file_monitor": ["user", "dev"],
            "cloud_sync": ["user", "dev"]
        }
        
        allowed_roles = module_rules.get(module_name, ["user", "dev"])
        return self.current_user["role"] in allowed_roles
    
    def get_user_data_path(self, subpath: str = "") -> Path:
        """Get the path to user's data directory."""
        if not self.current_user:
            raise ValueError("No user logged in")
        
        full_path = self.current_user["user_dir"] / subpath
        full_path.parent.mkdir(parents=True, exist_ok=True)
        return full_path
    
    def create_default_admin(self) -> bool:
        """Create a default admin user for initial setup."""
        try:
            # Check if any users exist
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM users")
                user_count = cursor.fetchone()[0]
                
                if user_count == 0:
                    # Create default admin user
                    success = self.create_user(
                        email="admin@cleanhouse.local",
                        password="admin123",
                        role="dev"
                    )
                    
                    if success:
                        logging.info("Default admin user created: admin@cleanhouse.local / admin123")
                        return True
                
                return False
                
        except Exception as e:
            logging.error(f"Failed to create default admin: {e}")
            return False

