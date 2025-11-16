# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - models/user_model.py
#  User model and service for account management
#  Devon • 2025‑01‑27
# ──────────────────────────────────────────────────────────────────────────────

# Optional bcrypt import (for password hashing)
try:
    import bcrypt
    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False
    bcrypt = None
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass
from .database import DatabaseManager
from .user_registry import UserRegistry, generate_user_id
from .shard_manager import ShardManager

@dataclass
class User:
    """
    User model representing a CleanHouse account.
    """
    id: Optional[int] = None  # Legacy: database ID (deprecated, kept for backward compatibility)
    user_id: Optional[str] = None  # New: sharded user ID (format: {normalized_email}_{timestamp})
    full_name: str = ""
    email: str = ""
    password_hash: str = ""
    role: str = "user"  # User role (default: "user")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    is_active: bool = True
    last_login: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert user to dictionary."""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'full_name': self.full_name,
            'email': self.email,
            'password_hash': self.password_hash,
            'role': self.role,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'is_active': self.is_active,
            'last_login': self.last_login.isoformat() if self.last_login else None
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'User':
        """Create user from dictionary."""
        # Handle datetime strings
        created_at = data.get('created_at')
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at)
            except (ValueError, AttributeError):
                created_at = None
        
        updated_at = data.get('updated_at')
        if isinstance(updated_at, str):
            try:
                updated_at = datetime.fromisoformat(updated_at)
            except (ValueError, AttributeError):
                updated_at = None
        
        last_login = data.get('last_login')
        if isinstance(last_login, str):
            try:
                last_login = datetime.fromisoformat(last_login)
            except (ValueError, AttributeError):
                last_login = None
        
        return cls(
            id=data.get('id'),
            user_id=data.get('user_id'),
            full_name=data.get('full_name', ''),
            email=data.get('email', ''),
            password_hash=data.get('password_hash', ''),
            role=data.get('role', 'user'),
            created_at=created_at,
            updated_at=updated_at,
            is_active=data.get('is_active', True),
            last_login=last_login
        )

class UserService:
    """
    Service for user account management using sharded file structure.
    Handles CRUD operations, authentication, and password management.
    Supports both sharded format (new) and SQLite (backward compatibility).
    """
    
    def __init__(self, cleanhouse_root: Path = None, db_manager: DatabaseManager = None):
        """
        Initialize UserService.
        
        Args:
            cleanhouse_root: Path to ~/.cleanhouse directory (defaults to ~/.cleanhouse)
            db_manager: Optional DatabaseManager for backward compatibility
        """
        # Determine cleanhouse root directory
        if cleanhouse_root is None:
            cleanhouse_root = Path.home() / ".cleanhouse"
        self.cleanhouse_root = Path(cleanhouse_root)
        self.cleanhouse_root.mkdir(parents=True, exist_ok=True)
        
        # Initialize sharded registry components
        self.user_registry = UserRegistry(self.cleanhouse_root)
        self.shard_manager = ShardManager(self.cleanhouse_root)
        
        # Keep db_manager for backward compatibility
        self.db_manager = db_manager
        
        # Feature flag: use sharded format (can be toggled for migration)
        self.use_sharded_format = True
        
        logging.info(f"UserService initialized with cleanhouse_root: {self.cleanhouse_root}")
    
    def create_user(self, full_name: str, email: str, password: str, invite_token: str = None, role: str = "user") -> User:
        """
        Create a new user account in sharded format.
        
        Args:
            full_name: User's full name
            email: User's email address
            password: Plain text password (will be hashed)
            invite_token: Optional invite token for developer mode
            role: User role (default: "user")
            
        Returns:
            User: Created user object
            
        Raises:
            ValueError: If email already exists or validation fails
            PermissionError: If access is denied in developer mode
        """
        # Check access control
        from access_control.access_control import access_control
        if not access_control.is_access_allowed(email, invite_token):
            raise PermissionError(access_control.get_access_denied_message())
        
        # Validate input
        if not email or not password or not full_name:
            raise ValueError("All fields are required")
        
        if not self._is_valid_email(email):
            raise ValueError("Invalid email format")
        
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters")
        
        # Check if email already exists
        if self.get_user_by_email(email):
            raise ValueError("Email already exists")
        
        # Generate user_id
        user_id = generate_user_id(email)
        
        # Calculate shard
        shard = self.shard_manager.get_user_shard(user_id)
        
        # Create directory structure
        user_dir = self.shard_manager.create_user_directory(user_id, shard)
        
        # Hash password
        password_hash = self._hash_password(password)
        
        # Create timestamp
        created_at = datetime.now()
        
        # Create identity/profile.json
        profile = {
            "user_id": user_id,
            "email": email,
            "full_name": full_name,
            "role": role,
            "created": created_at.isoformat(),
            "last_seen": created_at.isoformat(),
            "is_active": True,
            "updated_at": created_at.isoformat()
        }
        
        profile_path = user_dir / "identity" / "profile.json"
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        with open(profile_path, 'w', encoding='utf-8') as f:
            json.dump(profile, f, indent=2)
        
        # Create identity/auth.json
        auth = {
            "user_id": user_id,
            "password_hash": password_hash,
            "password_updated_at": created_at.isoformat(),
            "auth_tokens": [],
            "last_login": None
        }
        
        auth_path = user_dir / "identity" / "auth.json"
        with open(auth_path, 'w', encoding='utf-8') as f:
            json.dump(auth, f, indent=2)
        
        # Register user in global registry
        self.user_registry.register_user(
            user_id=user_id,
            email=email,
            full_name=full_name,
            shard=shard,
            created_at=created_at
        )
        
        # Create default preferences
        default_prefs = {
            "theme": "default",
            "scan_interval": 300,
            "notifications": True,
            "auto_scan": False
        }
        
        prefs_path = user_dir / "preferences" / "settings.json"
        prefs_path.parent.mkdir(parents=True, exist_ok=True)
        with open(prefs_path, 'w', encoding='utf-8') as f:
            json.dump(default_prefs, f, indent=2)
        
        logging.info(f"User created: {email} ({user_id}) in shard {shard}")
        
        # Return User object
        return User(
            user_id=user_id,
            full_name=full_name,
            email=email,
            password_hash=password_hash,
            role=role,
            created_at=created_at,
            updated_at=created_at,
            is_active=True
        )
    
    def get_user_by_email(self, email: str) -> Optional[User]:
        """
        Get user by email address.
        
        Args:
            email: User's email address
            
        Returns:
            User: User object if found, None otherwise
        """
        if self.use_sharded_format:
            # Lookup user_id from registry
            user_id = self.user_registry.get_user_id_by_email(email)
            if not user_id:
                # Fallback to SQLite for backward compatibility
                if self.db_manager:
                    return self._get_user_from_sqlite(email)
                return None
            
            # Load user from sharded structure
            return self._load_user_from_shard(user_id)
        else:
            # Legacy SQLite mode
            if self.db_manager:
                return self._get_user_from_sqlite(email)
            return None
    
    def _load_user_from_shard(self, user_id: str) -> Optional[User]:
        """
        Load user data from sharded directory structure.
        
        Args:
            user_id: User ID in format {normalized_email}_{timestamp}
            
        Returns:
            User: User object if found, None otherwise
        """
        user_path = self.shard_manager.get_user_path(user_id)
        
        # Load profile.json
        profile_path = user_path / "identity" / "profile.json"
        if not profile_path.exists():
            logging.warning(f"Profile not found for user_id: {user_id}")
            return None
        
        try:
            with open(profile_path, 'r', encoding='utf-8') as f:
                profile = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logging.error(f"Failed to load profile for user_id {user_id}: {e}")
            return None
        
        # Load auth.json for password hash
        auth_path = user_path / "identity" / "auth.json"
        password_hash = ""
        if auth_path.exists():
            try:
                with open(auth_path, 'r', encoding='utf-8') as f:
                    auth = json.load(f)
                    password_hash = auth.get("password_hash", "")
            except (json.JSONDecodeError, IOError) as e:
                logging.warning(f"Failed to load auth for user_id {user_id}: {e}")
        
        # Parse timestamps
        created_at = None
        if profile.get("created"):
            try:
                created_at = datetime.fromisoformat(profile["created"])
            except (ValueError, AttributeError):
                pass
        
        updated_at = created_at
        if profile.get("updated_at"):
            try:
                updated_at = datetime.fromisoformat(profile["updated_at"])
            except (ValueError, AttributeError):
                pass
        
        last_login = None
        if profile.get("last_seen"):
            try:
                last_login = datetime.fromisoformat(profile["last_seen"])
            except (ValueError, AttributeError):
                pass
        
        return User(
            user_id=user_id,
            full_name=profile.get("full_name", ""),
            email=profile.get("email", ""),
            password_hash=password_hash,
            role=profile.get("role", "user"),
            created_at=created_at,
            updated_at=updated_at,
            is_active=profile.get("is_active", True),
            last_login=last_login
        )
    
    def _get_user_from_sqlite(self, email: str) -> Optional[User]:
        """
        Fallback: Get user from SQLite (backward compatibility).
        
        Args:
            email: User's email address
            
        Returns:
            User: User object if found, None otherwise
        """
        if not self.db_manager:
            return None
        
        try:
            with self.db_manager as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
                row = cursor.fetchone()
                
                if row:
                    return User.from_dict(dict(row))
                return None
        except Exception as e:
            logging.error(f"Error loading user from SQLite: {e}")
            return None
    
    def get_user_by_id(self, user_id: str = None, legacy_id: int = None) -> Optional[User]:
        """
        Get user by ID (sharded user_id or legacy database id).
        
        Args:
            user_id: Sharded user ID (format: {normalized_email}_{timestamp}) or legacy int ID
            legacy_id: Legacy database ID (for backward compatibility, deprecated)
            
        Returns:
            User: User object if found, None otherwise
            
        Note:
            For backward compatibility, if user_id is an int, it's treated as legacy_id.
        """
        # Handle backward compatibility: if user_id is an int, treat it as legacy_id
        if isinstance(user_id, int):
            legacy_id = user_id
            user_id = None
        
        if self.use_sharded_format and user_id and isinstance(user_id, str):
            # Load from sharded structure
            return self._load_user_from_shard(user_id)
        elif legacy_id is not None and self.db_manager:
            # Legacy SQLite lookup
            try:
                with self.db_manager as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT * FROM users WHERE id = ?", (legacy_id,))
                    row = cursor.fetchone()
                    
                    if row:
                        return User.from_dict(dict(row))
                    return None
            except Exception as e:
                logging.error(f"Error loading user from SQLite by ID: {e}")
                return None
        return None
    
    def authenticate_user(self, email: str, password: str) -> Optional[User]:
        """
        Authenticate user with email and password.
        
        Args:
            email: User's email address
            password: Plain text password
            
        Returns:
            User: User object if authentication successful, None otherwise
        """
        user = self.get_user_by_email(email)
        if not user:
            return None
        
        if not user.is_active:
            logging.warning(f"Authentication failed for inactive user: {email}")
            return None
        
        # Load password hash from sharded format or use stored hash
        if self.use_sharded_format and user.user_id:
            # Load password hash from auth.json
            user_path = self.shard_manager.get_user_path(user.user_id)
            auth_path = user_path / "identity" / "auth.json"
            
            if auth_path.exists():
                try:
                    with open(auth_path, 'r', encoding='utf-8') as f:
                        auth = json.load(f)
                        stored_hash = auth.get("password_hash", "")
                except (json.JSONDecodeError, IOError) as e:
                    logging.error(f"Failed to load auth file for user {user.user_id}: {e}")
                    return None
            else:
                logging.error(f"Auth file not found for user {user.user_id}")
                return None
        else:
            # Use stored password hash (legacy mode)
            stored_hash = user.password_hash
        
        if self._verify_password(password, stored_hash):
            # Update last login
            if self.use_sharded_format and user.user_id:
                self._update_last_login(user.user_id)
                self.user_registry.update_last_seen(user.user_id)
            elif user.id:
                # Legacy SQLite update
                self._update_last_login_legacy(user.id)
            logging.info(f"User authenticated: {email}")
            return user
        
        logging.warning(f"Authentication failed for user: {email}")
        return None
    
    def update_user(self, user_id: str = None, legacy_id: int = None, **kwargs) -> bool:
        """
        Update user information.
        
        Args:
            user_id: Sharded user ID (format: {normalized_email}_{timestamp})
            legacy_id: Legacy database ID (for backward compatibility)
            **kwargs: Fields to update (full_name, email, is_active)
            
        Returns:
            bool: True if update successful, False otherwise
        """
        allowed_fields = ['full_name', 'email', 'is_active']
        update_fields = {k: v for k, v in kwargs.items() if k in allowed_fields}
        
        if not update_fields:
            return False
        
        if self.use_sharded_format and user_id:
            # Update sharded format
            user_path = self.shard_manager.get_user_path(user_id)
            profile_path = user_path / "identity" / "profile.json"
            
            if not profile_path.exists():
                logging.error(f"Profile not found for user_id: {user_id}")
                return False
            
            try:
                # Load existing profile
                with open(profile_path, 'r', encoding='utf-8') as f:
                    profile = json.load(f)
                
                # Update fields
                if 'full_name' in update_fields:
                    profile['full_name'] = update_fields['full_name']
                if 'email' in update_fields:
                    # Email change requires registry update
                    old_email = profile.get('email')
                    new_email = update_fields['email']
                    if old_email != new_email:
                        # Update registry email index
                        try:
                            self.user_registry.update_user_email(user_id, old_email, new_email)
                            profile['email'] = new_email
                        except Exception as e:
                            logging.error(f"Failed to update email in registry: {e}")
                            return False
                if 'is_active' in update_fields:
                    profile['is_active'] = update_fields['is_active']
                
                profile['updated_at'] = datetime.now().isoformat()
                
                # Atomic write
                temp_path = profile_path.with_suffix('.json.tmp')
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(profile, f, indent=2)
                temp_path.replace(profile_path)
                
                logging.info(f"User updated: {user_id}")
                return True
            except (json.JSONDecodeError, IOError) as e:
                logging.error(f"Failed to update user {user_id}: {e}")
                return False
        elif legacy_id is not None and self.db_manager:
            # Legacy SQLite update
            update_fields['updated_at'] = datetime.now()
            set_clause = ', '.join([f"{k} = ?" for k in update_fields.keys()])
            values = list(update_fields.values()) + [legacy_id]
            
            try:
                with self.db_manager as conn:
                    cursor = conn.cursor()
                    cursor.execute(f"""
                        UPDATE users 
                        SET {set_clause}
                        WHERE id = ?
                    """, values)
                    
                    conn.commit()
                    return cursor.rowcount > 0
            except Exception as e:
                logging.error(f"Failed to update user in SQLite: {e}")
                return False
        
        return False
    
    def delete_user(self, user_id: str = None, legacy_id: int = None) -> bool:
        """
        Delete user account.
        
        Args:
            user_id: Sharded user ID (format: {normalized_email}_{timestamp})
            legacy_id: Legacy database ID (for backward compatibility)
            
        Returns:
            bool: True if deletion successful, False otherwise
        """
        if self.use_sharded_format and user_id:
            # Delete from sharded format
            try:
                # Get user email before deletion for registry cleanup
                user = self._load_user_from_shard(user_id)
                email = user.email if user else None
                
                # Remove from registry
                if email:
                    self.user_registry.unregister_user(user_id, email)
                
                # Delete user directory
                user_path = self.shard_manager.get_user_path(user_id)
                if user_path.exists():
                    import shutil
                    shutil.rmtree(user_path)
                    logging.info(f"User directory deleted: {user_id}")
                
                logging.info(f"User deleted: {user_id}")
                return True
            except Exception as e:
                logging.error(f"Failed to delete user {user_id}: {e}")
                return False
        elif legacy_id is not None and self.db_manager:
            # Legacy SQLite deletion
            try:
                with self.db_manager as conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM users WHERE id = ?", (legacy_id,))
                    conn.commit()
                    
                    if cursor.rowcount > 0:
                        logging.info(f"User deleted: {legacy_id}")
                        return True
                    return False
            except Exception as e:
                logging.error(f"Failed to delete user from SQLite: {e}")
                return False
        
        return False
    
    def _hash_password(self, password: str) -> str:
        """
        Hash password using bcrypt.
        
        Args:
            password: Plain text password
            
        Returns:
            str: Hashed password
            
        Raises:
            RuntimeError: If bcrypt is not available
        """
        if not BCRYPT_AVAILABLE:
            raise RuntimeError("bcrypt is required for password hashing")
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
    
    def _verify_password(self, password: str, password_hash: str) -> bool:
        """
        Verify password against hash.
        
        Args:
            password: Plain text password
            password_hash: Hashed password
            
        Returns:
            bool: True if password matches, False otherwise
            
        Raises:
            RuntimeError: If bcrypt is not available
        """
        if not BCRYPT_AVAILABLE:
            raise RuntimeError("bcrypt is required for password verification")
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
    
    def _is_valid_email(self, email: str) -> bool:
        """
        Validate email format.
        
        Args:
            email: Email address to validate
            
        Returns:
            bool: True if valid, False otherwise
        """
        import re
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(pattern, email) is not None
    
    def _update_last_login(self, user_id: str):
        """
        Update user's last login timestamp in sharded format.
        
        Args:
            user_id: Sharded user ID (format: {normalized_email}_{timestamp})
        """
        user_path = self.shard_manager.get_user_path(user_id)
        auth_path = user_path / "identity" / "auth.json"
        
        if auth_path.exists():
            try:
                with open(auth_path, 'r', encoding='utf-8') as f:
                    auth = json.load(f)
                
                auth["last_login"] = datetime.now().isoformat()
                
                # Atomic write: write to temp file, then rename
                temp_path = auth_path.with_suffix('.json.tmp')
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(auth, f, indent=2)
                temp_path.replace(auth_path)
            except (json.JSONDecodeError, IOError) as e:
                logging.error(f"Failed to update last_login in auth.json for user {user_id}: {e}")
        
        # Also update profile.json
        profile_path = user_path / "identity" / "profile.json"
        if profile_path.exists():
            try:
                with open(profile_path, 'r', encoding='utf-8') as f:
                    profile = json.load(f)
                
                profile["last_seen"] = datetime.now().isoformat()
                profile["updated_at"] = datetime.now().isoformat()
                
                # Atomic write: write to temp file, then rename
                temp_path = profile_path.with_suffix('.json.tmp')
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(profile, f, indent=2)
                temp_path.replace(profile_path)
            except (json.JSONDecodeError, IOError) as e:
                logging.error(f"Failed to update last_seen in profile.json for user {user_id}: {e}")
    
    def _update_last_login_legacy(self, user_id: int):
        """
        Update user's last login timestamp in SQLite (legacy mode).
        
        Args:
            user_id: Legacy database ID
        """
        if not self.db_manager:
            return
        
        try:
            with self.db_manager as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE users 
                    SET last_login = ?, updated_at = ?
                    WHERE id = ?
                """, (datetime.now(), datetime.now(), user_id))
                conn.commit()
        except Exception as e:
            logging.error(f"Failed to update last_login in SQLite for user {user_id}: {e}")
