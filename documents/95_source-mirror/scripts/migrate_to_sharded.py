#!/usr/bin/env python3
# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - scripts/migrate_to_sharded.py
#  Migration script to convert SQLite users to sharded file format
#  Devon • 2025-11-13
# ──────────────────────────────────────────────────────────────────────────────

"""
Migration script to migrate existing SQLite users to sharded file format.

Usage:
    python scripts/migrate_to_sharded.py [--dry-run] [--cleanhouse-root PATH] [--db-path PATH]

Options:
    --dry-run              Show what would be migrated without making changes
    --cleanhouse-root      Path to ~/.cleanhouse directory (default: ~/.cleanhouse)
    --db-path              Path to SQLite database (default: ~/.cleanhouse/cleanhouse.db)
    --rollback             Rollback migration (removes sharded users, restores SQLite)
    --help                 Show this help message
"""

import sys
import argparse
import json
import logging
import sqlite3
import shutil
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from models.user_registry import UserRegistry, generate_user_id_from_existing, normalize_email_for_user_id
from models.shard_manager import ShardManager
from models.database import DatabaseManager


def setup_logging(verbose: bool = False):
    """Setup logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%I:%M:%S %p'
    )


def read_sqlite_users(db_path: Path) -> List[Dict[str, Any]]:
    """
    Read all users from SQLite database.
    
    Args:
        db_path: Path to SQLite database file
        
    Returns:
        List of user dictionaries
    """
    if not db_path.exists():
        logging.warning(f"Database not found: {db_path}")
        return []
    
    users = []
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, full_name, email, password_hash, created_at, updated_at, 
                   is_active, last_login
            FROM users
            ORDER BY id
        """)
        
        for row in cursor.fetchall():
            user_dict = dict(row)
            # Convert timestamps to datetime objects if they're strings
            for field in ['created_at', 'updated_at', 'last_login']:
                if user_dict.get(field) and isinstance(user_dict[field], str):
                    try:
                        user_dict[field] = datetime.fromisoformat(user_dict[field].replace('Z', '+00:00'))
                    except (ValueError, AttributeError):
                        # Keep as string if parsing fails
                        pass
            
            users.append(user_dict)
        
        conn.close()
        logging.info(f"Found {len(users)} users in SQLite database")
        return users
        
    except sqlite3.Error as e:
        logging.error(f"Error reading SQLite database: {e}")
        return []


def generate_user_id_for_migration(email: str, created_at: Optional[datetime] = None) -> str:
    """
    Generate user_id for migration, using existing timestamp if available.
    
    Args:
        email: User's email address
        created_at: Original creation timestamp (if available)
        
    Returns:
        user_id in format {normalized_email}_{timestamp}
    """
    if created_at and isinstance(created_at, datetime):
        # Use existing timestamp
        return generate_user_id_from_existing(email, created_at)
    else:
        # Use current timestamp
        from models.user_registry import generate_user_id
        return generate_user_id(email)


def migrate_user(
    user: Dict[str, Any],
    cleanhouse_root: Path,
    dry_run: bool = False
) -> bool:
    """
    Migrate a single user from SQLite to sharded format.
    
    Args:
        user: User dictionary from SQLite
        cleanhouse_root: Path to ~/.cleanhouse directory
        dry_run: If True, don't make actual changes
        
    Returns:
        True if migration successful, False otherwise
    """
    email = user.get('email')
    full_name = user.get('full_name', '')
    password_hash = user.get('password_hash', '')
    created_at = user.get('created_at')
    updated_at = user.get('updated_at', created_at)
    is_active = user.get('is_active', True)
    last_login = user.get('last_login')
    
    if not email:
        logging.error(f"User {user.get('id')} has no email, skipping")
        return False
    
    # Generate user_id
    user_id = generate_user_id_for_migration(email, created_at)
    
    # Calculate shard
    shard_manager = ShardManager(cleanhouse_root)
    shard = shard_manager.get_user_shard(user_id)
    
    logging.info(f"Migrating user: {email} -> {user_id} (shard: {shard})")
    
    if dry_run:
        logging.info(f"[DRY RUN] Would create user directory: {shard_manager.get_user_path(user_id)}")
        return True
    
    try:
        # Create directory structure
        user_dir = shard_manager.create_user_directory(user_id, shard)
        
        # Create identity/profile.json
        profile = {
            "user_id": user_id,
            "email": email,
            "full_name": full_name,
            "created": created_at.isoformat() if created_at else datetime.now().isoformat(),
            "last_seen": last_login.isoformat() if last_login else (created_at.isoformat() if created_at else datetime.now().isoformat()),
            "is_active": bool(is_active),
            "updated_at": updated_at.isoformat() if updated_at else (created_at.isoformat() if created_at else datetime.now().isoformat())
        }
        
        profile_path = user_dir / "identity" / "profile.json"
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        with open(profile_path, 'w', encoding='utf-8') as f:
            json.dump(profile, f, indent=2)
        
        # Create identity/auth.json
        auth = {
            "user_id": user_id,
            "password_hash": password_hash,
            "password_updated_at": updated_at.isoformat() if updated_at else (created_at.isoformat() if created_at else datetime.now().isoformat()),
            "auth_tokens": [],
            "last_login": last_login.isoformat() if last_login else None
        }
        
        auth_path = user_dir / "identity" / "auth.json"
        with open(auth_path, 'w', encoding='utf-8') as f:
            json.dump(auth, f, indent=2)
        
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
        
        # Register user in global registry
        user_registry = UserRegistry(cleanhouse_root)
        created_at_dt = created_at if isinstance(created_at, datetime) else datetime.now()
        user_registry.register_user(
            user_id=user_id,
            email=email,
            full_name=full_name,
            shard=shard,
            created_at=created_at_dt
        )
        
        logging.info(f"✓ Migrated user: {email} ({user_id})")
        return True
        
    except Exception as e:
        logging.error(f"✗ Failed to migrate user {email}: {e}")
        return False


def check_migration_status(cleanhouse_root: Path, db_path: Path) -> Dict[str, Any]:
    """
    Check migration status: how many users in SQLite vs sharded format.
    
    Args:
        cleanhouse_root: Path to ~/.cleanhouse directory
        db_path: Path to SQLite database
        
    Returns:
        Dictionary with migration status information
    """
    status = {
        'sqlite_users': 0,
        'sharded_users': 0,
        'migration_complete': False
    }
    
    # Count SQLite users
    if db_path.exists():
        users = read_sqlite_users(db_path)
        status['sqlite_users'] = len(users)
    
    # Count sharded users
    registry_path = cleanhouse_root / "users.json"
    if registry_path.exists():
        try:
            with open(registry_path, 'r', encoding='utf-8') as f:
                registry = json.load(f)
                status['sharded_users'] = len(registry.get("users", {}))
        except Exception as e:
            logging.warning(f"Failed to read registry: {e}")
    
    status['migration_complete'] = (
        status['sharded_users'] >= status['sqlite_users'] and
        status['sqlite_users'] > 0
    )
    
    return status


def rollback_migration(cleanhouse_root: Path, db_path: Path, backup_path: Optional[Path] = None):
    """
    Rollback migration by removing sharded users.
    
    Args:
        cleanhouse_root: Path to ~/.cleanhouse directory
        db_path: Path to SQLite database (for reference)
        backup_path: Optional path to SQLite backup to restore
    """
    logging.warning("ROLLBACK: Removing sharded user data...")
    
    # Remove users.json registry
    registry_path = cleanhouse_root / "users.json"
    if registry_path.exists():
        backup_registry = cleanhouse_root / "users.json.backup"
        if backup_registry.exists():
            logging.info(f"Restoring registry from backup: {backup_registry}")
            shutil.copy2(backup_registry, registry_path)
        else:
            logging.warning("No registry backup found, removing registry")
            registry_path.unlink()
    
    # Remove users directory
    users_dir = cleanhouse_root / "users"
    if users_dir.exists():
        logging.warning(f"Removing users directory: {users_dir}")
        shutil.rmtree(users_dir)
    
    # Restore SQLite backup if provided
    if backup_path and backup_path.exists():
        logging.info(f"Restoring SQLite database from backup: {backup_path}")
        shutil.copy2(backup_path, db_path)
    
    logging.info("Rollback complete")


def create_backup(db_path: Path) -> Optional[Path]:
    """
    Create a backup of the SQLite database.
    
    Args:
        db_path: Path to SQLite database
        
    Returns:
        Path to backup file, or None if backup failed
    """
    if not db_path.exists():
        return None
    
    backup_path = db_path.with_suffix('.db.backup')
    try:
        shutil.copy2(db_path, backup_path)
        logging.info(f"Created backup: {backup_path}")
        return backup_path
    except Exception as e:
        logging.error(f"Failed to create backup: {e}")
        return None


def main():
    """Main migration function."""
    parser = argparse.ArgumentParser(
        description='Migrate SQLite users to sharded file format',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be migrated without making changes'
    )
    parser.add_argument(
        '--cleanhouse-root',
        type=Path,
        default=Path.home() / ".cleanhouse",
        help='Path to ~/.cleanhouse directory (default: ~/.cleanhouse)'
    )
    parser.add_argument(
        '--db-path',
        type=Path,
        default=None,
        help='Path to SQLite database (default: ~/.cleanhouse/cleanhouse.db)'
    )
    parser.add_argument(
        '--rollback',
        action='store_true',
        help='Rollback migration (removes sharded users)'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Verbose logging'
    )
    
    args = parser.parse_args()
    
    setup_logging(args.verbose)
    
    # Determine database path
    if args.db_path is None:
        args.db_path = args.cleanhouse_root / "cleanhouse.db"
    
    # Ensure cleanhouse root exists
    args.cleanhouse_root.mkdir(parents=True, exist_ok=True)
    
    # Check migration status
    status = check_migration_status(args.cleanhouse_root, args.db_path)
    logging.info(f"Migration status: {status['sqlite_users']} SQLite users, {status['sharded_users']} sharded users")
    
    if args.rollback:
        rollback_migration(args.cleanhouse_root, args.db_path)
        return
    
    # Check if already migrated
    if status['migration_complete']:
        logging.warning("Migration appears to be complete. Use --rollback to undo.")
        response = input("Continue anyway? (y/N): ")
        if response.lower() != 'y':
            return
    
    # Read users from SQLite
    users = read_sqlite_users(args.db_path)
    
    if not users:
        logging.warning("No users found in SQLite database. Nothing to migrate.")
        return
    
    # Create backup
    if not args.dry_run:
        backup_path = create_backup(args.db_path)
        if not backup_path:
            logging.warning("Failed to create backup. Continue anyway? (y/N): ")
            response = input()
            if response.lower() != 'y':
                return
    
    # Migrate users
    logging.info(f"Starting migration of {len(users)} users...")
    if args.dry_run:
        logging.info("[DRY RUN MODE] No changes will be made")
    
    success_count = 0
    failed_count = 0
    
    for user in users:
        if migrate_user(user, args.cleanhouse_root, dry_run=args.dry_run):
            success_count += 1
        else:
            failed_count += 1
    
    # Summary
    logging.info("=" * 60)
    logging.info(f"Migration complete: {success_count} succeeded, {failed_count} failed")
    if args.dry_run:
        logging.info("[DRY RUN] No actual changes were made")
    else:
        logging.info(f"Users migrated to: {args.cleanhouse_root / 'users'}")
        logging.info("You can now use the sharded format. SQLite database is kept for backward compatibility.")


if __name__ == '__main__':
    main()

