# Investigation Prompt: Implementing VVAULT-Style User Registry with Shards for CleanHouse

**Date**: November 13, 2025  
**Context**: CleanHouse needs to migrate from a simple SQLite-based user registry to a sharded file-based user registry system, matching the architecture used in VVAULT.

---

## Objective

Investigate how to implement a **sharded user registry database** for CleanHouse that mirrors VVAULT's architecture. The goal is to:

1. **Clone VVAULT's file structure** with shards and user directories
2. **Maintain compatibility** with CleanHouse's existing authentication system
3. **Ensure scalability** to handle billions of users (via sharding)
4. **Preserve data isolation** between users

---

## Current CleanHouse Architecture

### File Structure

```
/cleanhouse/
├── models/
│   ├── __init__.py              # Exports: User, UserService, DatabaseManager
│   ├── database.py              # DatabaseManager class (SQLite, thread-safe)
│   └── user_model.py            # User dataclass + UserService class
├── ui/
│   ├── auth.py                  # AuthWindow (Tkinter auth UI)
│   ├── simple_webview_auth.py   # SimpleWebViewAuth (WebView auth)
│   ├── main.py                  # CleanHouseUI (main orchestrator)
│   └── user_manager.py          # UserManager (legacy, may be deprecated)
├── access_control/
│   └── access_control.py        # Developer-only access control
└── corefiles/
    └── brain.py                 # Entry point, sets up paths/logging
```

### Current User Registry Implementation

**Location**: `~/.cleanhouse/cleanhouse.db` (SQLite database)

**Schema** (`models/database.py`):
```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT 1,
    last_login TIMESTAMP NULL
)
```

**Key Components**:

1. **`DatabaseManager`** (`models/database.py`):
   - Thread-safe SQLite connection management
   - Uses `threading.local()` for thread-local connections
   - Initializes schema on first connection
   - Default path: `~/.cleanhouse/cleanhouse.db`

2. **`UserService`** (`models/user_model.py`):
   - CRUD operations: `create_user()`, `get_user_by_email()`, `authenticate_user()`, `update_user()`, `delete_user()`
   - Password hashing: bcrypt (with fallback)
   - Access control integration: checks `access_control` module
   - Returns `User` dataclass objects

3. **`User` dataclass** (`models/user_model.py`):
   - Fields: `id`, `full_name`, `email`, `password_hash`, `created_at`, `updated_at`, `is_active`, `last_login`
   - Methods: `to_dict()`, `from_dict()`

4. **Integration Points**:
   - `ui/simple_webview_auth.py`: Creates `DatabaseManager()` and `UserService(db_manager)` for signup/login
   - `ui/auth.py`: Uses `UserService` for Tkinter auth window
   - `ui/main.py`: Uses `UserManager` (legacy) for user data directories

### Current User Data Storage

**Location**: `userdata/{email_sanitized}/`

**Structure**:
```
userdata/
├── admin_at_cleanhouse_local/
│   ├── scan_results/
│   ├── logs/
│   └── preferences/
└── {user_email_sanitized}/
    ├── scan_results/
    ├── logs/
    └── preferences/
```

**Note**: Email sanitization: `email.replace("@", "_at_").replace(".", "_")`

---

## VVAULT Reference Architecture

### File Structure

```
/vvault/
├── users.json                    # Global user registry (JSON)
├── users/                        # All user data (SHARDED)
│   ├── shard_0000/
│   │   ├── {user_id_1}/
│   │   │   ├── identity/
│   │   │   │   └── profile.json
│   │   │   ├── constructs/
│   │   │   ├── capsules/
│   │   │   └── sessions/
│   │   ├── {user_id_2}/
│   │   └── ...
│   ├── shard_0001/
│   ├── shard_0002/
│   └── ... (up to shard_9999)
└── system/
    └── registry/
        ├── user_index.db
        └── construct_index.db
```

### Sharding Logic

**Shard Calculation** (`scripts/create_user_profile.py`):
```python
SHARD_COUNT = 10000  # 10,000 shards
SHARD_PADDING = 4    # shard_0000, shard_0001, ..., shard_9999

def get_user_shard(user_id: str) -> str:
    # Hash-based sharding (for production):
    hash_obj = hashlib.md5(user_id.encode('utf-8'))
    hash_int = int(hash_obj.hexdigest(), 16)
    shard_num = hash_int % SHARD_COUNT
    return f"shard_{shard_num:0{SHARD_PADDING}d}"
    
    # Sequential (for development):
    # return "shard_0000"
```

**User ID Format**: `{normalized_name}_{timestamp}` (e.g., `devon_woodson_1762969514958`)

**Shard Benefits**:
- ✅ Filesystem performance: Limits directory entries per shard
- ✅ Parallel processing: Shards can be processed independently
- ✅ Distributed storage: Each shard can be on separate backend
- ✅ Scalability: Handles billions of users without degradation

### User Registry Files

**1. Global Registry** (`users.json`):
```json
{
  "users": {
    "devon_woodson_1762969514958": {
      "id": "devon_woodson_1762969514958",
      "name": "Devon Woodson",
      "email": "dwoodson92@gmail.com",
      "created": "2025-11-12T12:45:14.993170",
      "last_seen": "2025-11-12T12:45:14.993174",
      "constructs": ["lin-001", "nova-001", ...],
      "storage_quota": "unlimited",
      "features": ["blockchain_identity", "capsule_encryption"]
    }
  }
}
```

**2. User Profile** (`users/{shard}/{user_id}/identity/profile.json`):
```json
{
  "user_id": "devon_woodson_1762969514958",
  "user_name": "Devon Woodson",
  "email": "dwoodson92@gmail.com",
  "created": "2024-01-01T12:34:56Z",
  "last_seen": "2024-11-10T23:45:00Z",
  "constructs": ["construct-a-001", "construct-b-001"],
  "storage_quota": "unlimited",
  "features": ["blockchain_identity", "capsule_encryption"]
}
```

### Key Implementation Files

**`scripts/create_user_profile.py`**:
- `normalize_name_for_user_id(name)`: Normalizes name for user ID
- `generate_user_id(name, timestamp)`: Creates `{name}_{timestamp}` user ID
- `get_user_shard(user_id)`: Calculates shard from user ID hash
- `create_user_profile(user_id, user_name, constructs)`: Creates full directory structure

---

## Investigation Tasks

### Task 1: Analyze File Structure Mapping

**Question**: How should CleanHouse's current user registry map to VVAULT's sharded structure?

**Considerations**:
- CleanHouse uses `email` as primary identifier; VVAULT uses `user_id` (name + timestamp)
- CleanHouse stores password hashes in SQLite; VVAULT stores in `identity/profile.json`?
- CleanHouse has `userdata/{email}/`; VVAULT has `users/{shard}/{user_id}/`
- CleanHouse needs: `scan_results/`, `logs/`, `preferences/`
- VVAULT has: `constructs/`, `capsules/`, `sessions/`, `identity/`

**Deliverable**: Mapping document showing:
- How `email` → `user_id` conversion works
- Where password hashes are stored (file vs. database)
- How CleanHouse-specific directories (`scan_results/`, `logs/`, `preferences/`) fit into sharded structure
- Whether to keep SQLite for auth or migrate to file-based

### Task 2: Design Shard Calculation Strategy

**Question**: How should CleanHouse calculate shards for users?

**Options**:
1. **Hash email** (like VVAULT hashes user_id): Consistent, but email can change
2. **Hash user_id** (after email → user_id conversion): Most consistent
3. **Hash database ID**: Requires database lookup first
4. **Sequential** (all to shard_0000): Simple for development

**Deliverable**: Recommendation with code example:
```python
def get_user_shard(email: str, user_id: str) -> str:
    # Your implementation
    pass
```

### Task 3: Design User ID Generation

**Question**: How should CleanHouse generate user IDs from emails/names?

**Current**: CleanHouse uses `email` as identifier  
**VVAULT**: Uses `{normalized_name}_{timestamp}` format

**Considerations**:
- CleanHouse signup collects: `full_name`, `email`, `password`, `role`
- Should user_id be: `{email_hash}`, `{normalized_name}_{timestamp}`, or `{email_normalized}_{timestamp}`?
- Need to maintain backward compatibility with existing users?

**Deliverable**: Function signature and implementation:
```python
def generate_user_id(full_name: str, email: str, timestamp: int = None) -> str:
    # Your implementation
    pass
```

### Task 4: Design Registry Storage Format

**Question**: Should CleanHouse use JSON (like VVAULT) or keep SQLite?

**Options**:
1. **JSON file** (`users.json`): Matches VVAULT, simple, but slower for large datasets
2. **SQLite** (`system/registry/user_index.db`): Fast queries, but adds database dependency
3. **Hybrid**: JSON for metadata, SQLite for auth (password hashes)

**Considerations**:
- CleanHouse already uses SQLite for auth (`cleanhouse.db`)
- VVAULT uses JSON for registry, but may have separate auth system
- Need fast email → user_id lookups for authentication

**Deliverable**: Recommendation with pros/cons and implementation sketch

### Task 5: Design Migration Strategy

**Question**: How to migrate existing CleanHouse users to sharded structure?

**Current State**:
- Users in `~/.cleanhouse/cleanhouse.db` (SQLite)
- User data in `userdata/{email_sanitized}/`

**Target State**:
- Users in `users/{shard}/{user_id}/identity/profile.json`
- User data in `users/{shard}/{user_id}/scan_results/`, `logs/`, `preferences/`
- Global registry in `users.json` or `system/registry/user_index.db`

**Deliverable**: Migration script outline:
```python
def migrate_existing_users():
    # 1. Read all users from cleanhouse.db
    # 2. Generate user_id for each
    # 3. Calculate shard
    # 4. Create directory structure
    # 5. Move user data
    # 6. Update registry
    # 7. Update authentication to use new structure
    pass
```

### Task 6: Design Authentication Integration

**Question**: How should `UserService` work with sharded file structure?

**Current Flow**:
1. `UserService.create_user()` → SQLite INSERT
2. `UserService.authenticate_user()` → SQLite SELECT + bcrypt verify
3. `UserService.get_user_by_email()` → SQLite SELECT

**New Flow** (with sharding):
1. `UserService.create_user()` → Generate user_id, calculate shard, create directories, write profile.json, update registry
2. `UserService.authenticate_user()` → Lookup user_id from registry (email → user_id), read profile.json, verify password
3. `UserService.get_user_by_email()` → Lookup user_id, read profile.json

**Deliverable**: Refactored `UserService` class design:
- How to find user by email (registry lookup)
- How to store/retrieve password hashes
- How to maintain thread-safety (if needed)
- How to handle concurrent access to JSON files

### Task 7: Design Directory Structure

**Question**: What should CleanHouse's sharded user directory structure look like?

**VVAULT Structure**:
```
users/{shard}/{user_id}/
├── identity/
│   └── profile.json
├── constructs/
├── capsules/
└── sessions/
```

**CleanHouse Needs**:
- `scan_results/` (file scan results)
- `logs/` (user-specific logs)
- `preferences/` (user settings)
- Password hash storage (where?)

**Deliverable**: Proposed structure:
```
users/{shard}/{user_id}/
├── identity/
│   ├── profile.json          # User metadata
│   └── auth.json             # Password hash, auth tokens?
├── scan_results/             # CleanHouse-specific
├── logs/                      # CleanHouse-specific
└── preferences/               # CleanHouse-specific
```

### Task 8: Design Backward Compatibility

**Question**: How to maintain compatibility during migration?

**Considerations**:
- Existing code expects `UserService` to work with SQLite
- Existing code expects `userdata/{email}/` structure
- Need gradual migration path (not breaking change)

**Deliverable**: Compatibility layer design:
- Wrapper that supports both old (SQLite) and new (sharded) formats
- Feature flag to enable sharded mode
- Fallback to SQLite if sharded structure not found

---

## File Connection Summary

### Current CleanHouse Flow

```
corefiles/brain.py
  └─> Sets up paths, logging, loads .env
      └─> ui/main.py (CleanHouseUI)
          └─> ui/simple_webview_auth.py (SimpleWebViewAuth)
              └─> models/database.py (DatabaseManager)
                  └─> models/user_model.py (UserService)
                      └─> access_control/access_control.py (access checks)
```

**Key Connections**:
1. **`brain.py`** → Sets `sys.path`, loads `.env`, configures logging
2. **`ui/main.py`** → Creates `SimpleWebViewAuth` instance, passes callbacks
3. **`ui/simple_webview_auth.py`** → Creates `DatabaseManager()` and `UserService(db_manager)`, calls `create_user()` / `authenticate_user()`
4. **`models/user_model.py`** → `UserService` uses `DatabaseManager.get_connection()` for SQLite queries
5. **`access_control/access_control.py`** → `UserService.create_user()` checks `access_control.is_access_allowed()`

### Proposed New Flow (with Sharding)

```
corefiles/brain.py
  └─> Sets up paths, logging, loads .env
      └─> ui/main.py (CleanHouseUI)
          └─> ui/simple_webview_auth.py (SimpleWebViewAuth)
              └─> models/user_registry.py (NEW: UserRegistry)
                  ├─> models/shard_manager.py (NEW: ShardManager)
                  └─> models/user_model.py (UserService - REFACTORED)
                      └─> access_control/access_control.py (access checks)
```

**New Components Needed**:
1. **`models/user_registry.py`**: Manages `users.json` or `system/registry/user_index.db`
   - `get_user_id_by_email(email) -> user_id`
   - `get_user_shard(user_id) -> shard_path`
   - `register_user(user_id, email, shard)`
   
2. **`models/shard_manager.py`**: Handles shard directory operations
   - `get_user_shard(user_id) -> str` (shard_XXXX)
   - `get_user_path(user_id) -> Path`
   - `create_user_directory(user_id, shard) -> Path`

3. **`models/user_model.py`** (REFACTORED): `UserService` now uses file-based storage
   - `create_user()` → Calls `ShardManager.create_user_directory()`, writes `identity/profile.json`
   - `authenticate_user()` → Looks up user_id from registry, reads `identity/auth.json` (or profile.json)
   - `get_user_by_email()` → Registry lookup → read profile.json

---

## Success Criteria

After investigation, you should provide:

1. ✅ **Complete file structure** for CleanHouse's sharded user registry
2. ✅ **Code examples** for all key functions (shard calculation, user_id generation, registry operations)
3. ✅ **Migration plan** from current SQLite to sharded file structure
4. ✅ **Integration plan** showing how `UserService` will work with new structure
5. ✅ **Backward compatibility** strategy (if needed)
6. ✅ **Testing strategy** to verify sharding works correctly

---

## Questions to Answer

1. **Should CleanHouse keep SQLite for authentication** (password hashes) and use JSON files for metadata, or migrate everything to file-based?

2. **How to handle email changes** if user_id is based on email? (VVAULT uses name + timestamp, so email can change)

3. **Should CleanHouse use `users.json` (like VVAULT) or `system/registry/user_index.db`** for the global registry?

4. **How to ensure thread-safety** when multiple threads access JSON registry files?

5. **What happens if a user's email is used to calculate shard**, but then email changes? (Shard should remain consistent)

6. **Should CleanHouse support both old (SQLite) and new (sharded) formats** during transition, or require full migration?

---

## Reference Files to Examine

**VVAULT**:
- `/Users/devonwoodson/Documents/GitHub/vvault/scripts/create_user_profile.py` - User creation logic
- `/Users/devonwoodson/Documents/GitHub/vvault/users.json` - Global registry format
- `/Users/devonwoodson/Documents/GitHub/vvault/VVAULT_FILE_STRUCTURE_SPEC.md` - Complete spec
- `/Users/devonwoodson/Documents/GitHub/vvault/users/shard_0000/` - Example shard structure

**CleanHouse**:
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/models/database.py` - Current DatabaseManager
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/models/user_model.py` - Current UserService
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/ui/simple_webview_auth.py` - How UserService is used
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/ui/user_manager.py` - Legacy UserManager (may be deprecated)

---

## Expected Deliverable

A comprehensive **implementation plan** document that includes:

1. **Architecture Design**: File structure, component responsibilities
2. **Code Specifications**: Function signatures, data structures, algorithms
3. **Migration Script**: Step-by-step migration from SQLite to sharded
4. **Integration Guide**: How to update existing code to use new structure
5. **Testing Plan**: How to verify sharding works correctly

**Format**: Markdown document with code examples, diagrams (ASCII or text), and clear explanations.

---

**End of Investigation Prompt**

