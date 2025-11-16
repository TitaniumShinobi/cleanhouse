# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - models/user_registry.py
#  Global user registry management (users.json)
#  Provides email → user_id lookups and user registration
#  Devon • 2025-11-13
# ──────────────────────────────────────────────────────────────────────────────

import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
import threading
import re
import shutil

logger = logging.getLogger(__name__)


def normalize_email_for_user_id(email: str) -> str:
    """
    Normalize email for use in user ID.
    - Convert to lowercase
    - Replace @ with _at_
    - Replace . with _
    - Replace + with _plus_ (preserve plus signs to avoid collisions)
    - Remove other special characters (keep only alphanumeric and underscores)
    - Limit length to 50 characters
    
    Args:
        email: User's email address
        
    Returns:
        str: Normalized email string
        
    Raises:
        ValueError: If email normalizes to empty string
        
    Example:
        "devon.woodson@example.com" → "devon_woodson_at_example_com"
        "user+tag@example.com" → "user_plus_tag_at_example_com"
    """
    if not email or not isinstance(email, str):
        raise ValueError('Email must be a non-empty string')
    
    normalized = email.lower().strip()
    normalized = normalized.replace('@', '_at_')
    normalized = normalized.replace('.', '_')
    normalized = normalized.replace('+', '_plus_')  # Preserve plus signs
    normalized = re.sub(r'[^a-z0-9_]', '', normalized)  # Remove other special chars
    normalized = normalized[:50]  # Limit length
    
    # Critical: Validate that normalization didn't result in empty string
    if not normalized:
        raise ValueError(f"Email '{email}' normalizes to empty string - cannot create user_id")
    
    return normalized


def generate_user_id(email: str, timestamp: int = None) -> str:
    """
    Generate a user ID in format: {normalized_email}_{timestamp}
    
    Args:
        email: User's email address
        timestamp: Optional timestamp in milliseconds (defaults to current time)
        
    Returns:
        str: User ID in format normalized_email_timestamp
        
    Example:
        generate_user_id("devon.woodson@example.com")
        # "devon_woodson_at_example_com_1733875200000"
    """
    normalized_email = normalize_email_for_user_id(email)
    auto_gen_timestamp = timestamp or int(datetime.now().timestamp() * 1000)  # milliseconds
    
    return f"{normalized_email}_{auto_gen_timestamp}"


def generate_user_id_from_existing(email: str, created_at: datetime) -> str:
    """
    Generate user_id for existing users using their creation timestamp.
    
    Args:
        email: User's email address
        created_at: User's creation timestamp from database
        
    Returns:
        str: User ID
    """
    normalized_email = normalize_email_for_user_id(email)
    timestamp_ms = int(created_at.timestamp() * 1000)
    return f"{normalized_email}_{timestamp_ms}"


class UserRegistry:
    """
    Manages global user registry (users.json).
    Provides email → user_id lookups and user registration.
    Thread-safe JSON file operations.
    """
    
    def __init__(self, cleanhouse_root: Path):
        """
        Initialize UserRegistry.
        
        Args:
            cleanhouse_root: Path to ~/.cleanhouse directory
        """
        self.cleanhouse_root = Path(cleanhouse_root)
        self.registry_path = self.cleanhouse_root / "users.json"
        self._lock = threading.RLock()  # Reentrant lock for thread safety
        
        # Initialize registry if it doesn't exist
        self._ensure_registry_exists()
    
    def _ensure_registry_exists(self):
        """Create registry file if it doesn't exist."""
        if not self.registry_path.exists():
            with self._lock:
                registry = {
                    "users": {},
                    "email_index": {}
                }
                self._write_registry(registry)
                logger.info(f"Created new user registry at {self.registry_path}")
    
    def _read_registry(self) -> Dict[str, Any]:
        """
        Read registry from JSON file (thread-safe) with corruption recovery.
        
        Returns:
            dict: Registry data with 'users' and 'email_index' keys
            
        Raises:
            RuntimeError: If registry is corrupted and backup unavailable
        """
        with self._lock:
            if not self.registry_path.exists():
                return {"users": {}, "email_index": {}}
            
            try:
                with open(self.registry_path, 'r', encoding='utf-8') as f:
                    registry = json.load(f)
                
                # Validate registry structure
                if not isinstance(registry, dict):
                    raise ValueError("Registry is not a dictionary")
                
                if "users" not in registry or "email_index" not in registry:
                    raise ValueError("Registry missing required keys: 'users' or 'email_index'")
                
                return registry
                
            except (json.JSONDecodeError, IOError, ValueError) as e:
                logger.error(f"Failed to read registry: {e}")
                
                # Try to restore from backup
                backup_path = self.registry_path.with_suffix('.json.backup')
                if backup_path.exists():
                    logger.warning(f"Attempting to restore registry from backup: {backup_path}")
                    try:
                        # Remove corrupted file first
                        if self.registry_path.exists():
                            self.registry_path.unlink()
                        # Restore from backup
                        shutil.copy2(backup_path, self.registry_path)
                        logger.info("Registry restored from backup successfully")
                        # Retry reading after restore (but don't recurse - read directly)
                        try:
                            with open(self.registry_path, 'r', encoding='utf-8') as f:
                                registry = json.load(f)
                            # Validate structure
                            if isinstance(registry, dict) and "users" in registry and "email_index" in registry:
                                return registry
                        except Exception as read_error:
                            logger.error(f"Failed to read restored registry: {read_error}")
                    except Exception as restore_error:
                        logger.error(f"Failed to restore registry from backup: {restore_error}")
                
                # Last resort: return empty but log critical error
                logger.critical(
                    "Registry corrupted and backup unavailable - "
                    "all users will appear missing. Manual intervention required."
                )
                return {"users": {}, "email_index": {}}
    
    def _write_registry(self, registry: Dict[str, Any]):
        """
        Write registry to JSON file (thread-safe with atomic operation and backup).
        
        Creates a backup before writing to enable recovery from corruption.
        
        Args:
            registry: Registry dictionary to write
            
        Raises:
            OSError: If disk is full (errno 28)
            PermissionError: If permission denied
            RuntimeError: For other write failures
        """
        with self._lock:
            # Create backup before write (if registry exists)
            if self.registry_path.exists():
                backup_path = self.registry_path.with_suffix('.json.backup')
                try:
                    shutil.copy2(self.registry_path, backup_path)
                    # Keep only last 5 backups (rotate old backups)
                    self._rotate_backups()
                except Exception as e:
                    logger.warning(f"Failed to create backup before write: {e}")
                    # Continue with write even if backup fails
            
            # Write to temporary file first, then rename (atomic operation)
            temp_path = self.registry_path.with_suffix('.json.tmp')
            try:
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(registry, f, indent=2, ensure_ascii=False)
                # Atomic rename (works on Unix and Windows)
                temp_path.replace(self.registry_path)
                logger.debug(f"Registry written successfully to {self.registry_path}")
            except OSError as e:
                if e.errno == 28:  # No space left on device
                    logger.critical("Disk full - cannot write registry")
                    raise RuntimeError("Disk full - cannot save user registry") from e
                raise
            except PermissionError as e:
                logger.critical(f"Permission denied writing registry: {e}")
                raise PermissionError(
                    f"Cannot write to {self.registry_path}. Check file permissions."
                ) from e
            except Exception as e:
                logger.error(f"Failed to write registry: {e}")
                # Clean up temp file if it exists
                if temp_path.exists():
                    temp_path.unlink()
                raise RuntimeError(f"Failed to write registry: {e}") from e
    
    def _rotate_backups(self, max_backups: int = 5):
        """
        Rotate backup files, keeping only the most recent N backups.
        
        Args:
            max_backups: Maximum number of backup files to keep
        """
        backup_pattern = self.registry_path.with_suffix('.json.backup')
        
        # Find all backup files
        backups = []
        for i in range(1, max_backups + 10):  # Check more than max to find all
            backup_file = backup_pattern if i == 1 else backup_pattern.with_suffix(f'.backup.{i}')
            if backup_file.exists():
                backups.append((backup_file.stat().st_mtime, backup_file))
        
        # Sort by modification time (newest first)
        backups.sort(reverse=True, key=lambda x: x[0])
        
        # Remove old backups beyond max_backups
        for _, backup_file in backups[max_backups:]:
            try:
                backup_file.unlink()
                logger.debug(f"Removed old backup: {backup_file}")
            except Exception as e:
                logger.warning(f"Failed to remove old backup {backup_file}: {e}")
    
    def get_user_id_by_email(self, email: str) -> Optional[str]:
        """
        Get user_id from email using email_index.
        
        Args:
            email: User's email address
            
        Returns:
            str: User ID if found, None otherwise
        """
        registry = self._read_registry()
        return registry.get("email_index", {}).get(email.lower())
    
    def register_user(
        self,
        user_id: str,
        email: str,
        full_name: str,
        shard: str,
        created_at: datetime = None
    ):
        """
        Register a new user in the global registry.
        
        Args:
            user_id: User ID
            email: User's email address
            full_name: User's full name
            shard: Shard name (e.g., "shard_0042")
            created_at: Creation timestamp
        """
        registry = self._read_registry()
        
        if created_at is None:
            created_at = datetime.now()
        
        # Check if user already exists
        if user_id in registry.get("users", {}):
            raise ValueError(f"User {user_id} already exists in registry")
        
        # Check if email already exists
        email_lower = email.lower()
        if email_lower in registry.get("email_index", {}):
            existing_user_id = registry["email_index"][email_lower]
            raise ValueError(
                f"Email {email} already registered to user {existing_user_id}"
            )
        
        # Add to users dict
        registry.setdefault("users", {})[user_id] = {
            "id": user_id,
            "email": email,
            "full_name": full_name,
            "created": created_at.isoformat(),
            "last_seen": created_at.isoformat(),
            "is_active": True,
            "shard": shard,
            "storage_quota": "unlimited"
        }
        
        # Add to email_index for fast lookup
        registry.setdefault("email_index", {})[email_lower] = user_id
        
        self._write_registry(registry)
        logger.info(f"Registered user {email} ({user_id}) in shard {shard}")
    
    def update_last_seen(self, user_id: str):
        """Update user's last_seen timestamp."""
        registry = self._read_registry()
        
        if user_id in registry.get("users", {}):
            registry["users"][user_id]["last_seen"] = datetime.now().isoformat()
            self._write_registry(registry)
    
    def get_user_metadata(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user metadata from registry."""
        registry = self._read_registry()
        return registry.get("users", {}).get(user_id)
    
    def update_user_email(self, user_id: str, old_email: str, new_email: str):
        """
        Update user's email address in registry.
        
        Args:
            user_id: User ID
            old_email: Old email address
            new_email: New email address
        """
        registry = self._read_registry()
        
        if user_id not in registry.get("users", {}):
            logger.warning(f"User {user_id} not found in registry")
            return
        
        # Update email in users dict
        registry["users"][user_id]["email"] = new_email
        
        # Update email_index
        old_email_lower = old_email.lower()
        new_email_lower = new_email.lower()
        
        if old_email_lower in registry.get("email_index", {}):
            del registry["email_index"][old_email_lower]
        
        registry.setdefault("email_index", {})[new_email_lower] = user_id
        
        self._write_registry(registry)
        logger.info(f"Updated email for user {user_id}: {old_email} → {new_email}")
    
    def user_exists(self, email: str) -> bool:
        """Check if a user exists by email."""
        return self.get_user_id_by_email(email) is not None
    
    def get_all_users(self) -> Dict[str, Dict[str, Any]]:
        """Get all users from registry."""
        registry = self._read_registry()
        return registry.get("users", {})
    
    def unregister_user(self, user_id: str, email: str):
        """
        Remove user from registry.
        
        Args:
            user_id: User ID
            email: User's email address
        """
        registry = self._read_registry()
        
        # Remove from users dict
        if user_id in registry.get("users", {}):
            del registry["users"][user_id]
        
        # Remove from email_index
        email_lower = email.lower()
        if email_lower in registry.get("email_index", {}):
            del registry["email_index"][email_lower]
        
        self._write_registry(registry)
        logger.info(f"Unregistered user {email} ({user_id})")

