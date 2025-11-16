# Sharded User Registry Implementation Review

**Date**: November 13, 2025  
**Reviewer**: Code Review  
**Status**: Edge Cases & Improvements Identified

---

## Executive Summary

This document identifies edge cases, potential improvements, and missing error handling in the sharded user registry implementation plan and Phase 1 code.

---

## Critical Issues

### 1. Email Normalization: Plus Signs Removed

**Issue**: Email addresses with plus signs (e.g., `user+tag@example.com`) have the `+` removed, which could cause collisions.

**Current Behavior**:
```python
normalized = re.sub(r'[^a-z0-9_]', '', normalized)  # Removes +
```

**Impact**: 
- `user+tag@example.com` → `usertag_at_example_com`
- `user@example.com` → `user_at_example_com` (if email is `user+@example.com`, it becomes `user_at_example_com`)
- Potential collision if two different emails normalize to the same string

**Recommendation**: Preserve plus signs or handle them explicitly:
```python
# Option 1: Preserve plus signs
normalized = normalized.replace('+', '_plus_')

# Option 2: Remove plus signs but add collision detection
# Check for collisions before creating user_id
```

**Priority**: Medium (unlikely but possible collision)

---

### 2. Empty String After Normalization

**Issue**: If email normalizes to empty string, `generate_user_id()` will create invalid user_id.

**Example**:
- Email: `+++@---.---` → normalizes to `""` → user_id: `_1234567890`

**Current Code**: No validation after normalization

**Recommendation**: Add validation:
```python
def normalize_email_for_user_id(email: str) -> str:
    # ... existing normalization ...
    normalized = normalized[:50]
    
    if not normalized:
        raise ValueError(f"Email '{email}' normalizes to empty string")
    
    return normalized
```

**Priority**: High (will cause invalid user_ids)

---

### 3. Registry Corruption Recovery

**Issue**: If `users.json` becomes corrupted, `_read_registry()` silently returns empty dict, losing all user data.

**Current Behavior**:
```python
except (json.JSONDecodeError, IOError) as e:
    logger.error(f"Failed to read registry: {e}")
    return {"users": {}, "email_index": {}}  # Silent failure
```

**Impact**: 
- All users appear to not exist
- Authentication fails for all users
- No recovery mechanism

**Recommendation**: 
1. Create backup before each write
2. Implement corruption detection and recovery
3. Add validation checksum or schema validation

```python
def _read_registry(self) -> Dict[str, Any]:
    """Read registry with corruption recovery."""
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
                raise ValueError("Registry missing required keys")
            
            return registry
            
        except (json.JSONDecodeError, IOError, ValueError) as e:
            logger.error(f"Failed to read registry: {e}")
            
            # Try to restore from backup
            backup_path = self.registry_path.with_suffix('.json.backup')
            if backup_path.exists():
                logger.warning(f"Attempting to restore from backup: {backup_path}")
                try:
                    shutil.copy2(backup_path, self.registry_path)
                    return self._read_registry()  # Retry
                except Exception as restore_error:
                    logger.error(f"Failed to restore from backup: {restore_error}")
            
            # Last resort: return empty but log critical error
            logger.critical("Registry corrupted and backup unavailable - all users will appear missing")
            return {"users": {}, "email_index": {}}
```

**Priority**: Critical (data loss risk)

---

### 4. Duplicate Email Registration: Silent Failure

**Issue**: `register_user()` silently returns if email already exists, but doesn't raise exception.

**Current Behavior**:
```python
if email_lower in registry.get("email_index", {}):
    existing_user_id = registry["email_index"][email_lower]
    logger.warning(f"Email {email} already registered to user {existing_user_id}")
    return  # Silent return
```

**Impact**: 
- Caller doesn't know registration failed
- Could lead to inconsistent state (directory created but not registered)

**Recommendation**: Raise exception:
```python
if email_lower in registry.get("email_index", {}):
    existing_user_id = registry["email_index"][email_lower]
    raise ValueError(f"Email {email} already registered to user {existing_user_id}")
```

**Priority**: High (inconsistent state risk)

---

### 5. User ID Collision Detection

**Issue**: Two users with same email at exact same millisecond could get same user_id.

**Probability**: Very low (1 in 1000 per millisecond), but possible in high-concurrency scenarios.

**Current Code**: No collision detection

**Recommendation**: Add collision detection:
```python
def generate_user_id(email: str, timestamp: int = None, registry: UserRegistry = None) -> str:
    """Generate user_id with collision detection."""
    normalized_email = normalize_email_for_user_id(email)
    auto_gen_timestamp = timestamp or int(datetime.now().timestamp() * 1000)
    
    user_id = f"{normalized_email}_{auto_gen_timestamp}"
    
    # Check for collision if registry provided
    if registry:
        max_attempts = 10
        attempt = 0
        while registry.get_user_metadata(user_id) is not None and attempt < max_attempts:
            # Increment timestamp by 1ms and retry
            auto_gen_timestamp += 1
            user_id = f"{normalized_email}_{auto_gen_timestamp}"
            attempt += 1
        
        if attempt >= max_attempts:
            raise RuntimeError(f"Unable to generate unique user_id for {email} after {max_attempts} attempts")
    
    return user_id
```

**Priority**: Low (very unlikely, but should be handled)

---

## Important Issues

### 6. Path Length Limits (Windows)

**Issue**: Windows has 260 character path limit. Long user_ids could exceed this.

**Example**:
- Base path: `C:\Users\username\.cleanhouse\users\shard_0042\`
- Long email: `very_long_email_address_with_many_characters_at_very_long_domain_name_example_com_1733875200000`
- Total: Could exceed 260 chars

**Current Code**: No validation

**Recommendation**: 
1. Add path length validation
2. Consider truncating user_id if needed (but ensure uniqueness)
3. Document Windows limitation

```python
def _validate_path_length(self, user_id: str) -> bool:
    """Check if user path would exceed filesystem limits."""
    user_path = self.get_user_path(user_id)
    path_str = str(user_path)
    
    # Windows MAX_PATH is 260 characters
    if len(path_str) > 260:
        logger.warning(f"User path exceeds 260 characters: {len(path_str)}")
        return False
    
    return True
```

**Priority**: Medium (Windows-specific issue)

---

### 7. Invalid Characters in User ID for Filesystem

**Issue**: Some filesystems don't allow certain characters in directory names.

**Current Code**: User_id uses only alphanumeric, underscores, and `_at_` (which is safe)

**Status**: ✅ Already handled (normalization removes invalid chars)

**Priority**: Low (already handled)

---

### 8. Disk Space Errors

**Issue**: No handling for disk full errors when writing registry or creating directories.

**Current Code**: Exceptions are caught but not specifically handled

**Recommendation**: Add specific error handling:
```python
def _write_registry(self, registry: Dict[str, Any]):
    """Write registry with disk space error handling."""
    with self._lock:
        temp_path = self.registry_path.with_suffix('.json.tmp')
        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(registry, f, indent=2, ensure_ascii=False)
            temp_path.replace(self.registry_path)
        except OSError as e:
            if e.errno == 28:  # No space left on device
                logger.critical("Disk full - cannot write registry")
                raise RuntimeError("Disk full - cannot save user registry") from e
            raise
        except Exception as e:
            # ... existing error handling ...
```

**Priority**: Medium (user experience issue)

---

### 9. Permission Errors

**Issue**: No handling for permission denied errors (read-only filesystem, insufficient permissions).

**Current Code**: Generic exception handling

**Recommendation**: Add specific error messages:
```python
def _write_registry(self, registry: Dict[str, Any]):
    """Write registry with permission error handling."""
    # ... existing code ...
    except PermissionError as e:
        logger.critical(f"Permission denied writing registry: {e}")
        raise PermissionError(
            f"Cannot write to {self.registry_path}. Check file permissions."
        ) from e
```

**Priority**: Medium (user experience issue)

---

### 10. Registry Backup Strategy

**Issue**: No automatic backup of `users.json` before writes.

**Current Code**: No backup mechanism

**Recommendation**: Implement backup before each write:
```python
def _write_registry(self, registry: Dict[str, Any]):
    """Write registry with backup."""
    with self._lock:
        # Create backup before write
        if self.registry_path.exists():
            backup_path = self.registry_path.with_suffix('.json.backup')
            try:
                shutil.copy2(self.registry_path, backup_path)
                # Keep only last 5 backups
                self._rotate_backups()
            except Exception as e:
                logger.warning(f"Failed to create backup: {e}")
        
        # ... existing write logic ...
```

**Priority**: High (data safety)

---

## Minor Issues & Improvements

### 11. Email Case Sensitivity in `update_user_email()`

**Issue**: `update_user_email()` doesn't validate that old_email matches current email in registry.

**Recommendation**: Add validation:
```python
def update_user_email(self, user_id: str, old_email: str, new_email: str):
    """Update email with validation."""
    registry = self._read_registry()
    
    if user_id not in registry.get("users", {}):
        raise ValueError(f"User {user_id} not found")
    
    current_email = registry["users"][user_id]["email"]
    if current_email.lower() != old_email.lower():
        raise ValueError(f"Old email '{old_email}' doesn't match current email '{current_email}'")
    
    # ... rest of method ...
```

**Priority**: Low (validation improvement)

---

### 12. Timestamp Validation

**Issue**: `generate_user_id()` accepts any integer as timestamp, including invalid values (negative, future, etc.).

**Recommendation**: Add validation:
```python
def generate_user_id(email: str, timestamp: int = None) -> str:
    """Generate user_id with timestamp validation."""
    normalized_email = normalize_email_for_user_id(email)
    
    if timestamp is None:
        timestamp = int(datetime.now().timestamp() * 1000)
    else:
        # Validate timestamp (reasonable range: 2000-01-01 to 2100-01-01)
        min_timestamp = 946684800000  # 2000-01-01
        max_timestamp = 4102444800000  # 2100-01-01
        
        if not (min_timestamp <= timestamp <= max_timestamp):
            raise ValueError(f"Timestamp {timestamp} out of valid range")
    
    return f"{normalized_email}_{timestamp}"
```

**Priority**: Low (defensive programming)

---

### 13. Registry Size Limits

**Issue**: Large `users.json` files could become slow to read/write (though unlikely with millions of users).

**Current Code**: No size limits or optimization

**Recommendation**: 
- Monitor registry size
- Consider splitting into multiple files if > 10MB
- Document performance characteristics

**Priority**: Low (future optimization)

---

### 14. Shard Directory Cleanup

**Issue**: Empty shard directories are never cleaned up.

**Recommendation**: Add cleanup utility:
```python
def cleanup_empty_shards(self):
    """Remove empty shard directories."""
    if not self.users_root.exists():
        return
    
    for item in self.users_root.iterdir():
        if item.is_dir() and item.name.startswith("shard_"):
            try:
                if not any(item.iterdir()):  # Empty directory
                    item.rmdir()
                    logger.info(f"Removed empty shard: {item.name}")
            except OSError:
                pass  # Directory not empty or permission error
```

**Priority**: Low (cleanup utility)

---

### 15. Migration Rollback Strategy

**Issue**: Migration script doesn't have detailed rollback strategy if migration fails partway.

**Recommendation**: 
1. Create transaction log
2. Implement checkpoint system
3. Add rollback function to undo partial migrations

**Priority**: Medium (migration safety)

---

## Security Considerations

### 16. Auth.json File Permissions

**Issue**: `identity/auth.json` contains password hashes but file permissions aren't set.

**Recommendation**: Set restrictive permissions:
```python
import os
import stat

def _write_auth_file(auth_path: Path, auth_data: Dict[str, Any]):
    """Write auth.json with restrictive permissions."""
    with open(auth_path, 'w') as f:
        json.dump(auth_data, f, indent=2)
    
    # Set permissions: owner read/write only (0600)
    os.chmod(auth_path, stat.S_IRUSR | stat.S_IWUSR)
```

**Priority**: High (security best practice)

---

### 17. Registry File Permissions

**Issue**: `users.json` contains user metadata but permissions aren't set.

**Recommendation**: Set appropriate permissions (readable by owner, not world-readable):
```python
def _write_registry(self, registry: Dict[str, Any]):
    """Write registry with secure permissions."""
    # ... existing write logic ...
    
    # Set permissions: owner read/write, group read (0640)
    os.chmod(self.registry_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)
```

**Priority**: Medium (security best practice)

---

## Performance Considerations

### 18. Registry Lock Contention

**Issue**: `RLock()` could cause contention with many concurrent reads.

**Current Code**: All operations (read and write) use the same lock

**Recommendation**: Use read-write lock for better concurrency:
```python
import threading

class ReadWriteLock:
    """Read-write lock for better concurrency."""
    def __init__(self):
        self._read_ready = threading.Condition(threading.RLock())
        self._readers = 0
    
    def acquire_read(self):
        with self._read_ready:
            self._readers += 1
    
    def release_read(self):
        with self._read_ready:
            self._readers -= 1
            if self._readers == 0:
                self._read_ready.notifyAll()
    
    def acquire_write(self):
        self._read_ready.acquire()
        while self._readers > 0:
            self._read_ready.wait()
    
    def release_write(self):
        self._read_ready.release()
```

**Priority**: Low (optimization for high concurrency)

---

### 19. Registry Caching

**Issue**: Registry is read from disk on every operation.

**Recommendation**: Add in-memory cache with periodic refresh:
```python
class UserRegistry:
    def __init__(self, cleanhouse_root: Path, cache_ttl: int = 5):
        # ... existing init ...
        self._cache = None
        self._cache_timestamp = 0
        self._cache_ttl = cache_ttl  # seconds
    
    def _read_registry(self, use_cache: bool = True) -> Dict[str, Any]:
        """Read registry with caching."""
        now = time.time()
        
        if use_cache and self._cache and (now - self._cache_timestamp) < self._cache_ttl:
            return self._cache
        
        # Read from disk
        registry = self._read_registry_from_disk()
        
        # Update cache
        self._cache = registry
        self._cache_timestamp = now
        
        return registry
```

**Priority**: Low (optimization)

---

## Testing Gaps

### 20. Missing Test Cases

**Identified Missing Tests**:
1. Email normalization edge cases (empty, special chars, unicode)
2. Shard calculation consistency (same user_id → same shard)
3. Concurrent registry access (thread safety)
4. Registry corruption recovery
5. Path length limits
6. Disk full scenarios
7. Permission error scenarios
8. User ID collision handling

**Priority**: Medium (test coverage)

---

## Documentation Gaps

### 21. Missing Documentation

**Identified Gaps**:
1. Windows path length limitations
2. File permission requirements
3. Backup and recovery procedures
4. Migration rollback procedures
5. Performance characteristics (registry size limits)
6. Shard distribution algorithm details

**Priority**: Low (documentation)

---

## Summary of Recommendations

### Critical (Must Fix)
1. ✅ Registry corruption recovery
2. ✅ Duplicate email registration exception
3. ✅ Empty string after normalization validation

### High Priority (Should Fix)
4. ✅ Registry backup strategy
5. ✅ Auth.json file permissions
6. ✅ Email normalization: plus sign handling

### Medium Priority (Consider Fixing)
7. Path length validation (Windows)
8. Disk space error handling
9. Permission error handling
10. Migration rollback strategy
11. Registry file permissions

### Low Priority (Nice to Have)
12. User ID collision detection
13. Email update validation
14. Timestamp validation
15. Registry size monitoring
16. Shard cleanup utility
17. Read-write lock optimization
18. Registry caching
19. Additional test cases
20. Documentation improvements

---

## Implementation Priority

**Phase 1.5 (Before Phase 2)**: Fix critical issues
- Registry corruption recovery
- Duplicate email exception
- Empty string validation
- Registry backup

**Phase 2.5 (During Phase 2)**: Fix high priority issues
- Auth.json permissions
- Plus sign handling
- File permissions

**Phase 3+ (Future)**: Address medium/low priority items as needed

---

**End of Review**

