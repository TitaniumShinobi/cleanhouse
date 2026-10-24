# CleanHouse Sharded User Registry Implementation Plan

**Date**: November 13, 2025  
**Status**: Investigation Complete - Ready for Implementation  
**Author**: Investigation Report

---

## Executive Summary

This document provides a comprehensive implementation plan for migrating CleanHouse from a SQLite-based user registry to a VVAULT-style sharded file-based user registry system. The plan addresses all investigation questions, provides code specifications, migration strategies, and integration guidelines.

**Key Decisions**:
1. **User ID Format**: `{normalized_email}_{timestamp}` (email-based, not name-based)
2. **Shard Calculation**: Hash-based using MD5 of user_id (consistent shard assignment)
3. **Registry Format**: Hybrid approach - JSON for metadata, separate auth.json for password hashes
4. **Migration Strategy**: Gradual migration with backward compatibility layer
5. **Directory Structure**: CleanHouse-specific directories integrated into VVAULT-style sharding

---

## Table of Contents

1. [File Structure Mapping](#1-file-structure-mapping)
2. [Shard Calculation Strategy](#2-shard-calculation-strategy)
3. [User ID Generation](#3-user-id-generation)
4. [Registry Storage Format](#4-registry-storage-format)
5. [Migration Strategy](#5-migration-strategy)
6. [Authentication Integration](#6-authentication-integration)
7. [Directory Structure Design](#7-directory-structure-design)
8. [Backward Compatibility](#8-backward-compatibility)
9. [Implementation Roadmap](#9-implementation-roadmap)
10. [Testing Strategy](#10-testing-strategy)

---

## 1. File Structure Mapping

### 1.1 Current CleanHouse Structure

```
~/.cleanhouse/
├── cleanhouse.db              # SQLite database (users table)
└── userdata/
    └── {email_sanitized}/     # email.replace("@", "_at_").replace(".", "_")
        ├── scan_results/
        ├── logs/
        └── preferences/
```

### 1.2 Target Sharded Structure

```
~/.cleanhouse/
├── users.json                  # Global user registry (email → user_id mapping)
├── users/                      # Sharded user data
│   ├── shard_0000/
│   │   ├── {user_id_1}/
│   │   │   ├── identity/
│   │   │   │   ├── profile.json      # User metadata (name, email, created, etc.)
│   │   │   │   └── auth.json         # Password hash, auth tokens (encrypted)
│   │   │   ├── scan_results/         # CleanHouse-specific
│   │   │   ├── logs/                 # CleanHouse-specific
│   │   │   └── preferences/          # CleanHouse-specific
│   │   └── {user_id_2}/
│   ├── shard_0001/
│   └── ... (up to shard_9999)
└── system/
    └── registry/
        └── user_index.db      # Optional: Fast email → user_id lookup (SQLite)
```

### 1.3 Mapping Decisions

| Current | Target | Notes |
|---------|--------|-------|
| `cleanhouse.db` (SQLite) | `users.json` + `identity/auth.json` | Split metadata and auth |
| `email` (primary key) | `user_id` (primary key) | Email → user_id via registry |
| `userdata/{email_sanitized}/` | `users/{shard}/{user_id}/` | Sharded structure |
| `userdata/{email}/scan_results/` | `users/{shard}/{user_id}/scan_results/` | Preserved structure |
| `userdata/{email}/logs/` | `users/{shard}/{user_id}/logs/` | Preserved structure |
| `userdata/{email}/preferences/` | `users/{shard}/{user_id}/preferences/` | Preserved structure |

### 1.4 Email → User ID Conversion

**Strategy**: Use email as base for user_id (not name) because:
- Email is unique and already used for authentication
- Name can change, email is more stable
- Maintains backward compatibility with existing email-based lookups

**Format**: `{normalized_email}_{timestamp}`

**Example**:
- Email: `devon.woodson@example.com`
- Normalized: `devon_woodson_at_example_com`
- Timestamp: `1733875200000` (milliseconds)
- User ID: `devon_woodson_at_example_com_1733875200000`

---

## 2. Shard Calculation Strategy

### 2.1 Recommendation: Hash-Based Sharding

**Use**: Hash `user_id` (not email) for shard calculation

**Rationale**:
- ✅ Consistent: Same user_id always maps to same shard
- ✅ Email changes don't affect shard (user_id doesn't change)
- ✅ Even distribution across 10,000 shards
- ✅ Scalable to billions of users

### 2.2 Implementation

```python
import hashlib
from pathlib import Path

# Sharding configuration
SHARD_COUNT = 10000  # 10,000 shards
SHARD_PADDING = 4    # shard_0000, shard_0001, ..., shard_9999

def get_user_shard(user_id: str) -> str:
    """
    Determine which shard a user belongs to using hash-based sharding.
    
    Args:
        user_id: User ID in format {normalized_email}_{timestamp}
        
    Returns:
        str: Shard name (e.g., "shard_0000", "shard_0042", "shard_9999")
    """
    # Hash user_id using MD5
    hash_obj = hashlib.md5(user_id.encode('utf-8'))
    hash_int = int(hash_obj.hexdigest(), 16)
    shard_num = hash_int % SHARD_COUNT
    
    return f"shard_{shard_num:0{SHARD_PADDING}d}"

# Example usage
user_id = "devon_woodson_at_example_com_1733875200000"
shard = get_user_shard(user_id)  # e.g., "shard_0042"
```

### 2.3 Development Mode

For development/testing, use sequential sharding (all users to shard_0000):

```python
def get_user_shard(user_id: str, dev_mode: bool = False) -> str:
    """Get user shard with optional dev mode."""
    if dev_mode:
        return "shard_0000"  # All users to first shard in dev mode
    
    # Production: hash-based sharding
    hash_obj = hashlib.md5(user_id.encode('utf-8'))
    hash_int = int(hash_obj.hexdigest(), 16)
    shard_num = hash_int % SHARD_COUNT
    return f"shard_{shard_num:0{SHARD_PADDING}d}"
```

---

## 3. User ID Generation

### 3.1 Normalization Function

```python
import re
from datetime import datetime

def normalize_email_for_user_id(email: str) -> str:
    """
    Normalize email for use in user ID.
    - Convert to lowercase
    - Replace @ with _at_
    - Replace . with _
    - Remove special characters (keep only alphanumeric and underscores)
    - Limit length to 50 characters
    
    Args:
        email: User's email address
        
    Returns:
        str: Normalized email string
        
    Example:
        "devon.woodson@example.com" → "devon_woodson_at_example_com"
    """
    if not email or not isinstance(email, str):
        raise ValueError('Email must be a non-empty string')
    
    normalized = email.lower().strip()
    normalized = normalized.replace('@', '_at_')
    normalized = normalized.replace('.', '_')
    normalized = re.sub(r'[^a-z0-9_]', '', normalized)  # Remove special chars
    return normalized[:50]  # Limit length
```

### 3.2 User ID Generation

```python
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
```

### 3.3 Backward Compatibility

For existing users, generate user_id from existing database records:

```python
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
```

---

## 4. Registry Storage Format

### 4.1 Recommendation: Hybrid Approach

**Decision**: Use **JSON for metadata** + **Separate auth.json for passwords**

**Rationale**:
- ✅ JSON is human-readable and matches VVAULT architecture
- ✅ Password hashes stored separately for security (can be encrypted)
- ✅ Fast email → user_id lookups via JSON (or optional SQLite index)
- ✅ Maintains compatibility with existing authentication flow

### 4.2 Global Registry: `users.json`

**Location**: `~/.cleanhouse/users.json`

**Format**:
```json
{
  "users": {
    "devon_woodson_at_example_com_1733875200000": {
      "id": "devon_woodson_at_example_com_1733875200000",
      "email": "devon.woodson@example.com",
      "full_name": "Devon Woodson",
      "created": "2025-11-13T12:34:56.789012",
      "last_seen": "2025-11-13T15:45:00.123456",
      "is_active": true,
      "shard": "shard_0042",
      "storage_quota": "unlimited"
    }
  },
  "email_index": {
    "devon.woodson@example.com": "devon_woodson_at_example_com_1733875200000",
    "admin@cleanhouse.local": "admin_at_cleanhouse_local_1730000000000"
  }
}
```

**Key Features**:
- `users` object: Full user metadata indexed by user_id
- `email_index` object: Fast email → user_id lookup (O(1) access)

### 4.3 User Profile: `identity/profile.json`

**Location**: `users/{shard}/{user_id}/identity/profile.json`

**Format**:
```json
{
  "user_id": "devon_woodson_at_example_com_1733875200000",
  "email": "devon.woodson@example.com",
  "full_name": "Devon Woodson",
  "created": "2025-11-13T12:34:56.789012",
  "last_seen": "2025-11-13T15:45:00.123456",
  "is_active": true,
  "updated_at": "2025-11-13T15:45:00.123456"
}
```

### 4.4 Authentication Data: `identity/auth.json`

**Location**: `users/{shard}/{user_id}/identity/auth.json`

**Format**:
```json
{
  "user_id": "devon_woodson_at_example_com_1733875200000",
  "password_hash": "$2b$12$...",  # bcrypt hash
  "password_updated_at": "2025-11-13T12:34:56.789012",
  "auth_tokens": [],  # Future: session tokens, API keys
  "last_login": "2025-11-13T15:45:00.123456"
}
```

**Security Note**: This file can be encrypted at rest in the future.

### 4.5 Optional: SQLite Index for Fast Lookups

**Location**: `~/.cleanhouse/system/registry/user_index.db`

**Schema**:
```sql
CREATE TABLE IF NOT EXISTS email_to_user_id (
    email TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    shard TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_user_id ON email_to_user_id(user_id);
CREATE INDEX IF NOT EXISTS idx_shard ON email_to_user_id(shard);
```

**Usage**: Optional performance optimization for systems with millions of users. JSON `email_index` is sufficient for most use cases.

---

## 5. Migration Strategy

### 5.1 Migration Phases

**Phase 1: Preparation** (Non-breaking)
- Create new sharded directory structure
- Implement `UserRegistry` and `ShardManager` classes
- Add feature flag for sharded mode

**Phase 2: Data Migration** (One-time)
- Read all users from `cleanhouse.db`
- Generate user_ids for existing users
- Create sharded directory structure
- Copy user data from `userdata/` to `users/{shard}/{user_id}/`
- Create `users.json` registry
- Create `identity/profile.json` and `identity/auth.json` for each user

**Phase 3: Dual-Mode Operation** (Transition)
- Support both SQLite and sharded formats
- New users created in sharded format
- Existing users can use either format (fallback to SQLite)
- Update authentication to check sharded format first, then SQLite

**Phase 4: Full Migration** (Breaking)
- All users migrated to sharded format
- Remove SQLite dependency
- Remove backward compatibility layer
- Archive `cleanhouse.db` and `userdata/` directories

### 5.2 Migration Script Outline

```python
#!/usr/bin/env python3
"""
Migrate CleanHouse users from SQLite to sharded file structure.
"""

import sqlite3
import json
import shutil
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

from models.shard_manager import ShardManager
from models.user_registry import UserRegistry

def migrate_existing_users(
    db_path: Path,
    cleanhouse_root: Path,
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Migrate all users from SQLite database to sharded file structure.
    
    Args:
        db_path: Path to existing cleanhouse.db
        cleanhouse_root: Path to ~/.cleanhouse directory
        dry_run: If True, don't make changes, just report
        
    Returns:
        dict: Migration report with statistics
    """
    # Initialize managers
    shard_manager = ShardManager(cleanhouse_root)
    user_registry = UserRegistry(cleanhouse_root)
    
    # Statistics
    stats = {
        "total_users": 0,
        "migrated": 0,
        "failed": 0,
        "errors": []
    }
    
    # Step 1: Read all users from SQLite
    logging.info(f"Reading users from {db_path}")
    users = read_users_from_sqlite(db_path)
    stats["total_users"] = len(users)
    
    if dry_run:
        logging.info(f"DRY RUN: Would migrate {len(users)} users")
        return stats
    
    # Step 2: Migrate each user
    for user in users:
        try:
            migrate_user(user, shard_manager, user_registry, cleanhouse_root)
            stats["migrated"] += 1
            logging.info(f"Migrated user: {user['email']}")
        except Exception as e:
            stats["failed"] += 1
            stats["errors"].append({
                "email": user.get("email", "unknown"),
                "error": str(e)
            })
            logging.error(f"Failed to migrate user {user.get('email')}: {e}")
    
    # Step 3: Create backup of original database
    backup_path = db_path.parent / f"cleanhouse.db.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    if not dry_run:
        shutil.copy2(db_path, backup_path)
        logging.info(f"Created backup: {backup_path}")
    
    return stats

def read_users_from_sqlite(db_path: Path) -> List[Dict[str, Any]]:
    """Read all users from SQLite database."""
    users = []
    
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users")
        
        for row in cursor.fetchall():
            users.append(dict(row))
    
    return users

def migrate_user(
    user: Dict[str, Any],
    shard_manager: ShardManager,
    user_registry: UserRegistry,
    cleanhouse_root: Path
):
    """
    Migrate a single user to sharded structure.
    
    Steps:
    1. Generate user_id from email and created_at
    2. Calculate shard
    3. Create directory structure
    4. Copy user data from userdata/ to users/{shard}/{user_id}/
    5. Create identity/profile.json
    6. Create identity/auth.json (with password hash)
    7. Update global registry (users.json)
    """
    email = user["email"]
    full_name = user.get("full_name", "")
    created_at = datetime.fromisoformat(user["created_at"]) if isinstance(user["created_at"], str) else user["created_at"]
    
    # Step 1: Generate user_id
    from models.user_registry import generate_user_id_from_existing
    user_id = generate_user_id_from_existing(email, created_at)
    
    # Step 2: Calculate shard
    shard = shard_manager.get_user_shard(user_id)
    
    # Step 3: Create directory structure
    user_dir = shard_manager.create_user_directory(user_id, shard)
    
    # Step 4: Copy user data
    old_userdata_dir = cleanhouse_root / "userdata" / email.replace("@", "_at_").replace(".", "_")
    if old_userdata_dir.exists():
        # Copy scan_results, logs, preferences
        for subdir in ["scan_results", "logs", "preferences"]:
            old_path = old_userdata_dir / subdir
            new_path = user_dir / subdir
            if old_path.exists():
                shutil.copytree(old_path, new_path, dirs_exist_ok=True)
                logging.info(f"Copied {subdir} for {email}")
    
    # Step 5: Create identity/profile.json
    profile = {
        "user_id": user_id,
        "email": email,
        "full_name": full_name,
        "created": created_at.isoformat(),
        "last_seen": user.get("last_login", created_at.isoformat()) if user.get("last_login") else created_at.isoformat(),
        "is_active": bool(user.get("is_active", True)),
        "updated_at": user.get("updated_at", created_at.isoformat())
    }
    
    profile_path = user_dir / "identity" / "profile.json"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    with open(profile_path, 'w') as f:
        json.dump(profile, f, indent=2)
    
    # Step 6: Create identity/auth.json
    auth = {
        "user_id": user_id,
        "password_hash": user["password_hash"],
        "password_updated_at": created_at.isoformat(),
        "auth_tokens": [],
        "last_login": user.get("last_login", created_at.isoformat()) if user.get("last_login") else None
    }
    
    auth_path = user_dir / "identity" / "auth.json"
    with open(auth_path, 'w') as f:
        json.dump(auth, f, indent=2)
    
    # Step 7: Update global registry
    user_registry.register_user(
        user_id=user_id,
        email=email,
        full_name=full_name,
        shard=shard,
        created_at=created_at
    )
    
    logging.info(f"Successfully migrated user {email} to {user_dir}")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Migrate CleanHouse users to sharded structure")
    parser.add_argument("--db-path", type=Path, help="Path to cleanhouse.db")
    parser.add_argument("--cleanhouse-root", type=Path, help="Path to ~/.cleanhouse")
    parser.add_argument("--dry-run", action="store_true", help="Dry run (don't make changes)")
    
    args = parser.parse_args()
    
    # Default paths
    if not args.cleanhouse_root:
        args.cleanhouse_root = Path.home() / ".cleanhouse"
    
    if not args.db_path:
        args.db_path = args.cleanhouse_root / "cleanhouse.db"
    
    logging.basicConfig(level=logging.INFO)
    
    stats = migrate_existing_users(
        db_path=args.db_path,
        cleanhouse_root=args.cleanhouse_root,
        dry_run=args.dry_run
    )
    
    print("\n" + "="*50)
    print("Migration Report")
    print("="*50)
    print(f"Total users: {stats['total_users']}")
    print(f"Migrated: {stats['migrated']}")
    print(f"Failed: {stats['failed']}")
    if stats['errors']:
        print("\nErrors:")
        for error in stats['errors']:
            print(f"  - {error['email']}: {error['error']}")
```

---

## 6. Authentication Integration

### 6.1 Refactored UserService Design

**New Architecture**:
- `UserService` uses `UserRegistry` for email → user_id lookups
- `UserService` uses `ShardManager` for directory operations
- Password hashes stored in `identity/auth.json`
- User metadata stored in `identity/profile.json`

### 6.2 UserRegistry Class

```python
# models/user_registry.py

import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
import threading

class UserRegistry:
    """
    Manages global user registry (users.json).
    Provides email → user_id lookups and user registration.
    Thread-safe JSON file operations.
    """
    
    def __init__(self, cleanhouse_root: Path):
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
    
    def _read_registry(self) -> Dict[str, Any]:
        """Read registry from JSON file (thread-safe)."""
        with self._lock:
            if not self.registry_path.exists():
                return {"users": {}, "email_index": {}}
            
            try:
                with open(self.registry_path, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logging.error(f"Failed to read registry: {e}")
                return {"users": {}, "email_index": {}}
    
    def _write_registry(self, registry: Dict[str, Any]):
        """Write registry to JSON file (thread-safe)."""
        with self._lock:
            # Write to temporary file first, then rename (atomic operation)
            temp_path = self.registry_path.with_suffix('.json.tmp')
            with open(temp_path, 'w') as f:
                json.dump(registry, f, indent=2)
            temp_path.replace(self.registry_path)
    
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
        registry.setdefault("email_index", {})[email.lower()] = user_id
        
        self._write_registry(registry)
        logging.info(f"Registered user {email} ({user_id}) in shard {shard}")
    
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
```

### 6.3 ShardManager Class

```python
# models/shard_manager.py

import hashlib
from pathlib import Path
from typing import Optional
import logging

# Sharding configuration
SHARD_COUNT = 10000
SHARD_PADDING = 4

class ShardManager:
    """
    Manages shard directory operations.
    Handles shard calculation and user directory creation.
    """
    
    def __init__(self, cleanhouse_root: Path, dev_mode: bool = False):
        self.cleanhouse_root = Path(cleanhouse_root)
        self.users_root = self.cleanhouse_root / "users"
        self.dev_mode = dev_mode
        
        # Create users root directory
        self.users_root.mkdir(parents=True, exist_ok=True)
    
    def get_user_shard(self, user_id: str) -> str:
        """
        Calculate shard for a user_id.
        
        Args:
            user_id: User ID
            
        Returns:
            str: Shard name (e.g., "shard_0000")
        """
        if self.dev_mode:
            return "shard_0000"  # All users to first shard in dev mode
        
        # Hash-based sharding
        hash_obj = hashlib.md5(user_id.encode('utf-8'))
        hash_int = int(hash_obj.hexdigest(), 16)
        shard_num = hash_int % SHARD_COUNT
        
        return f"shard_{shard_num:0{SHARD_PADDING}d}"
    
    def get_user_path(self, user_id: str) -> Path:
        """
        Get full path to user's directory.
        
        Args:
            user_id: User ID
            
        Returns:
            Path: Full path to user directory
        """
        shard = self.get_user_shard(user_id)
        return self.users_root / shard / user_id
    
    def create_user_directory(self, user_id: str, shard: Optional[str] = None) -> Path:
        """
        Create user directory structure.
        
        Args:
            user_id: User ID
            shard: Optional shard name (calculated if not provided)
            
        Returns:
            Path: Created user directory path
        """
        if shard is None:
            shard = self.get_user_shard(user_id)
        
        user_dir = self.users_root / shard / user_id
        
        # Create directory structure
        (user_dir / "identity").mkdir(parents=True, exist_ok=True)
        (user_dir / "scan_results").mkdir(parents=True, exist_ok=True)
        (user_dir / "logs").mkdir(parents=True, exist_ok=True)
        (user_dir / "preferences").mkdir(parents=True, exist_ok=True)
        
        logging.info(f"Created user directory: {user_dir}")
        return user_dir
    
    def user_directory_exists(self, user_id: str) -> bool:
        """Check if user directory exists."""
        user_path = self.get_user_path(user_id)
        return user_path.exists() and (user_path / "identity" / "profile.json").exists()
```

### 6.4 Refactored UserService

```python
# models/user_model.py (REFACTORED)

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any
from dataclasses import dataclass

try:
    import bcrypt
    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False
    bcrypt = None

from .user_registry import UserRegistry
from .shard_manager import ShardManager
from .user_registry import generate_user_id, normalize_email_for_user_id

@dataclass
class User:
    """User model (unchanged from current implementation)."""
    id: Optional[int] = None  # Legacy: database ID (deprecated)
    user_id: Optional[str] = None  # New: sharded user ID
    full_name: str = ""
    email: str = ""
    password_hash: str = ""
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
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'is_active': self.is_active,
            'last_login': self.last_login.isoformat() if self.last_login else None
        }

class UserService:
    """
    Service for user account management using sharded file structure.
    """
    
    def __init__(self, cleanhouse_root: Path, db_manager=None):
        """
        Initialize UserService.
        
        Args:
            cleanhouse_root: Path to ~/.cleanhouse directory
            db_manager: Optional DatabaseManager for backward compatibility
        """
        self.cleanhouse_root = Path(cleanhouse_root)
        self.user_registry = UserRegistry(self.cleanhouse_root)
        self.shard_manager = ShardManager(self.cleanhouse_root)
        self.db_manager = db_manager  # For backward compatibility
        
        # Feature flag: use sharded format
        self.use_sharded_format = True
    
    def create_user(
        self,
        full_name: str,
        email: str,
        password: str,
        invite_token: str = None
    ) -> User:
        """
        Create a new user account in sharded format.
        
        Args:
            full_name: User's full name
            email: User's email address
            password: Plain text password (will be hashed)
            invite_token: Optional invite token for developer mode
            
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
            "created": created_at.isoformat(),
            "last_seen": created_at.isoformat(),
            "is_active": True,
            "updated_at": created_at.isoformat()
        }
        
        profile_path = user_dir / "identity" / "profile.json"
        with open(profile_path, 'w') as f:
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
        with open(auth_path, 'w') as f:
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
        with open(prefs_path, 'w') as f:
            json.dump(default_prefs, f, indent=2)
        
        logging.info(f"User created: {email} ({user_id}) in shard {shard}")
        
        # Return User object
        return User(
            user_id=user_id,
            full_name=full_name,
            email=email,
            password_hash=password_hash,
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
        # Lookup user_id from registry
        user_id = self.user_registry.get_user_id_by_email(email)
        if not user_id:
            # Fallback to SQLite for backward compatibility
            if self.db_manager and not self.use_sharded_format:
                return self._get_user_from_sqlite(email)
            return None
        
        # Load user from sharded structure
        return self._load_user_from_shard(user_id)
    
    def _load_user_from_shard(self, user_id: str) -> Optional[User]:
        """Load user data from sharded directory structure."""
        user_path = self.shard_manager.get_user_path(user_id)
        
        # Load profile.json
        profile_path = user_path / "identity" / "profile.json"
        if not profile_path.exists():
            return None
        
        with open(profile_path, 'r') as f:
            profile = json.load(f)
        
        # Load auth.json for password hash
        auth_path = user_path / "identity" / "auth.json"
        password_hash = ""
        if auth_path.exists():
            with open(auth_path, 'r') as f:
                auth = json.load(f)
                password_hash = auth.get("password_hash", "")
        
        # Parse timestamps
        created_at = datetime.fromisoformat(profile["created"]) if profile.get("created") else None
        updated_at = datetime.fromisoformat(profile.get("updated_at", profile["created"])) if profile.get("updated_at") else created_at
        last_login = datetime.fromisoformat(profile["last_seen"]) if profile.get("last_seen") else None
        
        return User(
            user_id=user_id,
            full_name=profile.get("full_name", ""),
            email=profile.get("email", ""),
            password_hash=password_hash,
            created_at=created_at,
            updated_at=updated_at,
            is_active=profile.get("is_active", True),
            last_login=last_login
        )
    
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
        
        # Load password hash from auth.json
        user_path = self.shard_manager.get_user_path(user.user_id)
        auth_path = user_path / "identity" / "auth.json"
        
        if not auth_path.exists():
            logging.error(f"Auth file not found for user {user.user_id}")
            return None
        
        with open(auth_path, 'r') as f:
            auth = json.load(f)
            stored_hash = auth.get("password_hash", "")
        
        if self._verify_password(password, stored_hash):
            # Update last login
            self._update_last_login(user.user_id)
            self.user_registry.update_last_seen(user.user_id)
            logging.info(f"User authenticated: {email}")
            return user
        
        logging.warning(f"Authentication failed for user: {email}")
        return None
    
    def _update_last_login(self, user_id: str):
        """Update user's last login timestamp."""
        user_path = self.shard_manager.get_user_path(user_id)
        auth_path = user_path / "identity" / "auth.json"
        
        if auth_path.exists():
            with open(auth_path, 'r') as f:
                auth = json.load(f)
            
            auth["last_login"] = datetime.now().isoformat()
            
            with open(auth_path, 'w') as f:
                json.dump(auth, f, indent=2)
        
        # Also update profile.json
        profile_path = user_path / "identity" / "profile.json"
        if profile_path.exists():
            with open(profile_path, 'r') as f:
                profile = json.load(f)
            
            profile["last_seen"] = datetime.now().isoformat()
            
            with open(profile_path, 'w') as f:
                json.dump(profile, f, indent=2)
    
    def _hash_password(self, password: str) -> str:
        """Hash password using bcrypt."""
        if not BCRYPT_AVAILABLE:
            raise RuntimeError("bcrypt is required for password hashing")
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
    
    def _verify_password(self, password: str, password_hash: str) -> bool:
        """Verify password against hash."""
        if not BCRYPT_AVAILABLE:
            raise RuntimeError("bcrypt is required for password verification")
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
    
    def _is_valid_email(self, email: str) -> bool:
        """Validate email format."""
        import re
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(pattern, email) is not None
    
    def _get_user_from_sqlite(self, email: str) -> Optional[User]:
        """Fallback: Get user from SQLite (backward compatibility)."""
        if not self.db_manager:
            return None
        
        # Use existing SQLite-based implementation
        # (Keep current implementation for backward compatibility)
        pass  # Implementation omitted for brevity
```

---

## 7. Directory Structure Design

### 7.1 Complete Directory Structure

```
~/.cleanhouse/
├── users.json                          # Global registry
├── users/                              # Sharded user data
│   ├── shard_0000/
│   │   ├── {user_id_1}/
│   │   │   ├── identity/
│   │   │   │   ├── profile.json        # User metadata
│   │   │   │   └── auth.json          # Password hash, auth tokens
│   │   │   ├── scan_results/          # CleanHouse: File scan results
│   │   │   └── ...
│   │   │   ├── logs/                  # CleanHouse: User-specific logs
│   │   │   └── ...
│   │   │   └── preferences/           # CleanHouse: User settings
│   │   │       └── settings.json
│   │   └── {user_id_2}/
│   ├── shard_0001/
│   └── ... (up to shard_9999)
└── system/                             # System-level data (optional)
    └── registry/
        └── user_index.db              # Optional: SQLite index for fast lookups
```

### 7.2 File Formats

#### `identity/profile.json`
```json
{
  "user_id": "devon_woodson_at_example_com_1733875200000",
  "email": "devon.woodson@example.com",
  "full_name": "Devon Woodson",
  "created": "2025-11-13T12:34:56.789012",
  "last_seen": "2025-11-13T15:45:00.123456",
  "is_active": true,
  "updated_at": "2025-11-13T15:45:00.123456"
}
```

#### `identity/auth.json`
```json
{
  "user_id": "devon_woodson_at_example_com_1733875200000",
  "password_hash": "$2b$12$...",
  "password_updated_at": "2025-11-13T12:34:56.789012",
  "auth_tokens": [],
  "last_login": "2025-11-13T15:45:00.123456"
}
```

#### `preferences/settings.json`
```json
{
  "theme": "default",
  "scan_interval": 300,
  "notifications": true,
  "auto_scan": false
}
```

---

## 8. Backward Compatibility

### 8.1 Compatibility Layer Design

**Strategy**: Support both SQLite and sharded formats during transition period.

**Implementation**:
1. Feature flag: `use_sharded_format` (default: `True` for new installs, `False` for existing)
2. Fallback logic: Check sharded format first, then SQLite
3. Migration detection: Automatically detect if users have been migrated

### 8.2 Compatibility Wrapper

```python
class UserService:
    def __init__(self, cleanhouse_root: Path, db_manager=None):
        self.cleanhouse_root = Path(cleanhouse_root)
        self.db_manager = db_manager
        
        # Detect if sharded format is available
        self.use_sharded_format = self._detect_sharded_format()
        
        if self.use_sharded_format:
            self.user_registry = UserRegistry(self.cleanhouse_root)
            self.shard_manager = ShardManager(self.cleanhouse_root)
    
    def _detect_sharded_format(self) -> bool:
        """Detect if sharded format is available."""
        users_json = self.cleanhouse_root / "users.json"
        users_dir = self.cleanhouse_root / "users"
        return users_json.exists() and users_dir.exists()
    
    def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user with fallback to SQLite."""
        # Try sharded format first
        if self.use_sharded_format:
            user = self._get_user_from_sharded(email)
            if user:
                return user
        
        # Fallback to SQLite
        if self.db_manager:
            return self._get_user_from_sqlite(email)
        
        return None
```

### 8.3 Migration Detection

```python
def is_migration_complete(cleanhouse_root: Path) -> bool:
    """Check if all users have been migrated to sharded format."""
    users_json = cleanhouse_root / "users.json"
    db_path = cleanhouse_root / "cleanhouse.db"
    
    if not users_json.exists():
        return False
    
    # Count users in registry vs database
    with open(users_json, 'r') as f:
        registry = json.load(f)
        registry_count = len(registry.get("users", {}))
    
    if not db_path.exists():
        return registry_count > 0
    
    # Count users in SQLite
    import sqlite3
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        db_count = cursor.fetchone()[0]
    
    # Migration complete if registry has all users
    return registry_count >= db_count
```

---

## 9. Implementation Roadmap

### Phase 1: Core Infrastructure (Week 1)
- [ ] Create `models/user_registry.py` (UserRegistry class)
- [ ] Create `models/shard_manager.py` (ShardManager class)
- [ ] Implement shard calculation functions
- [ ] Implement user_id generation functions
- [ ] Create directory structure creation logic
- [ ] Unit tests for sharding and user_id generation

### Phase 2: UserService Refactoring (Week 2)
- [ ] Refactor `UserService` to use sharded format
- [ ] Implement `create_user()` with sharded structure
- [ ] Implement `authenticate_user()` with sharded structure
- [ ] Implement `get_user_by_email()` with registry lookup
- [ ] Add backward compatibility layer
- [ ] Integration tests for authentication flow

### Phase 3: Migration Script (Week 3)
- [ ] Create migration script (`scripts/migrate_to_sharded.py`)
- [ ] Implement user data copying logic
- [ ] Implement registry update logic
- [ ] Add dry-run mode
- [ ] Add rollback capability
- [ ] Test migration on development database

### Phase 4: UI Integration (Week 4)
- [ ] Update `ui/simple_webview_auth.py` to use new UserService
- [ ] Update `ui/auth.py` to use new UserService
- [ ] Update `ui/main.py` to use new user directory paths
- [ ] Test signup/login flows
- [ ] Test user data access

### Phase 5: Testing & Validation (Week 5)
- [ ] End-to-end testing
- [ ] Performance testing (shard lookup speed)
- [ ] Concurrent access testing (thread safety)
- [ ] Migration validation on production-like data
- [ ] Documentation updates

### Phase 6: Deployment (Week 6)
- [ ] Deploy to staging environment
- [ ] Run migration on staging
- [ ] Validate all functionality
- [ ] Deploy to production
- [ ] Monitor for issues

---

## 10. Testing Strategy

### 10.1 Unit Tests

**Test Shard Calculation**:
```python
def test_shard_calculation():
    """Test that same user_id always maps to same shard."""
    shard_manager = ShardManager(Path("/tmp/test"))
    user_id = "test_user_1234567890"
    shard1 = shard_manager.get_user_shard(user_id)
    shard2 = shard_manager.get_user_shard(user_id)
    assert shard1 == shard2  # Consistent sharding
```

**Test User ID Generation**:
```python
def test_user_id_generation():
    """Test user_id format and uniqueness."""
    email = "test@example.com"
    user_id1 = generate_user_id(email)
    user_id2 = generate_user_id(email)
    assert user_id1 != user_id2  # Different timestamps
    assert user_id1.startswith("test_at_example_com_")  # Correct format
```

### 10.2 Integration Tests

**Test User Creation**:
```python
def test_create_user_sharded():
    """Test creating user in sharded format."""
    cleanhouse_root = Path("/tmp/test_cleanhouse")
    user_service = UserService(cleanhouse_root)
    
    user = user_service.create_user(
        full_name="Test User",
        email="test@example.com",
        password="password123"
    )
    
    assert user.user_id is not None
    assert user.email == "test@example.com"
    
    # Verify directory structure exists
    user_path = user_service.shard_manager.get_user_path(user.user_id)
    assert (user_path / "identity" / "profile.json").exists()
    assert (user_path / "identity" / "auth.json").exists()
    assert (user_path / "scan_results").exists()
```

**Test Authentication**:
```python
def test_authenticate_user_sharded():
    """Test authentication with sharded format."""
    cleanhouse_root = Path("/tmp/test_cleanhouse")
    user_service = UserService(cleanhouse_root)
    
    # Create user
    user_service.create_user(
        full_name="Test User",
        email="test@example.com",
        password="password123"
    )
    
    # Authenticate
    authenticated = user_service.authenticate_user(
        email="test@example.com",
        password="password123"
    )
    
    assert authenticated is not None
    assert authenticated.email == "test@example.com"
```

### 10.3 Migration Tests

**Test Migration**:
```python
def test_migrate_existing_users():
    """Test migrating users from SQLite to sharded format."""
    # Create test SQLite database with users
    # Run migration script
    # Verify all users migrated
    # Verify data integrity
    pass
```

---

## 11. Answers to Investigation Questions

### Q1: Should CleanHouse keep SQLite for authentication or migrate everything to file-based?

**Answer**: **Hybrid approach** - Use JSON for metadata (`users.json` + `identity/profile.json`) and separate `identity/auth.json` for password hashes. This provides:
- Human-readable metadata (JSON)
- Security separation (auth.json can be encrypted)
- Fast lookups (email_index in users.json)
- Optional SQLite index for very large user bases

### Q2: How to handle email changes if user_id is based on email?

**Answer**: **User_id never changes** - Once generated, user_id remains constant even if email changes. Email changes are handled by:
1. Updating `email_index` in `users.json` (old email → new email)
2. Updating `profile.json` with new email
3. Keeping user_id unchanged (ensures shard consistency)

### Q3: Should CleanHouse use `users.json` or `system/registry/user_index.db`?

**Answer**: **Use `users.json`** for primary registry. Optional SQLite index (`user_index.db`) can be added later for performance optimization if needed (millions of users). JSON is sufficient for most use cases and matches VVAULT architecture.

### Q4: How to ensure thread-safety when multiple threads access JSON registry files?

**Answer**: **Use `threading.RLock()`** (reentrant lock) in `UserRegistry` class:
- All registry read/write operations are wrapped in lock
- Atomic file writes (write to temp file, then rename)
- Thread-safe JSON operations

### Q5: What happens if a user's email is used to calculate shard, but then email changes?

**Answer**: **Shard is calculated from user_id, not email** - Since user_id never changes (contains timestamp), shard assignment remains consistent even if email changes. This ensures user data stays in the same shard.

### Q6: Should CleanHouse support both old (SQLite) and new (sharded) formats during transition?

**Answer**: **Yes** - Implement backward compatibility layer:
- Feature flag: `use_sharded_format`
- Fallback logic: Check sharded format first, then SQLite
- Gradual migration: New users use sharded format, existing users can use either
- Migration script: One-time migration of all existing users

---

## 12. Code Examples Summary

### Key Functions

1. **Shard Calculation**:
```python
def get_user_shard(user_id: str) -> str:
    hash_obj = hashlib.md5(user_id.encode('utf-8'))
    hash_int = int(hash_obj.hexdigest(), 16)
    shard_num = hash_int % 10000
    return f"shard_{shard_num:04d}"
```

2. **User ID Generation**:
```python
def generate_user_id(email: str, timestamp: int = None) -> str:
    normalized = normalize_email_for_user_id(email)
    timestamp = timestamp or int(datetime.now().timestamp() * 1000)
    return f"{normalized}_{timestamp}"
```

3. **Email Normalization**:
```python
def normalize_email_for_user_id(email: str) -> str:
    normalized = email.lower().replace('@', '_at_').replace('.', '_')
    normalized = re.sub(r'[^a-z0-9_]', '', normalized)
    return normalized[:50]
```

---

## 13. Conclusion

This implementation plan provides a complete roadmap for migrating CleanHouse to a VVAULT-style sharded user registry system. The design:

- ✅ Maintains compatibility with existing authentication flow
- ✅ Provides scalability to billions of users via sharding
- ✅ Preserves data isolation between users
- ✅ Supports gradual migration with backward compatibility
- ✅ Includes comprehensive testing strategy
- ✅ Answers all investigation questions

**Next Steps**: Begin Phase 1 implementation (Core Infrastructure).

---

**End of Implementation Plan**


