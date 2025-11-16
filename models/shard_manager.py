# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - models/shard_manager.py
#  Shard directory operations and management
#  Handles shard calculation and user directory creation
#  Devon • 2025-11-13
# ──────────────────────────────────────────────────────────────────────────────

import hashlib
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Sharding configuration
SHARD_COUNT = 10000  # 10,000 shards = ~100,000 users per shard at 1 billion users
SHARD_PADDING = 4    # shard_0000, shard_0001, ..., shard_9999


def get_user_shard(user_id: str, dev_mode: bool = False) -> str:
    """
    Determine which shard a user belongs to using hash-based sharding.
    
    Args:
        user_id: User ID in format {normalized_email}_{timestamp}
        dev_mode: If True, all users go to shard_0000 (for development)
        
    Returns:
        str: Shard name (e.g., "shard_0000", "shard_0042", "shard_9999")
    """
    if dev_mode:
        return "shard_0000"  # All users to first shard in dev mode
    
    # Hash-based sharding
    hash_obj = hashlib.md5(user_id.encode('utf-8'))
    hash_int = int(hash_obj.hexdigest(), 16)
    shard_num = hash_int % SHARD_COUNT
    
    return f"shard_{shard_num:0{SHARD_PADDING}d}"


class ShardManager:
    """
    Manages shard directory operations.
    Handles shard calculation and user directory creation.
    """
    
    def __init__(self, cleanhouse_root: Path, dev_mode: bool = False):
        """
        Initialize ShardManager.
        
        Args:
            cleanhouse_root: Path to ~/.cleanhouse directory
            dev_mode: If True, all users go to shard_0000 (for development)
        """
        self.cleanhouse_root = Path(cleanhouse_root)
        self.users_root = self.cleanhouse_root / "users"
        self.dev_mode = dev_mode
        
        # Create users root directory
        self.users_root.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Initialized ShardManager with root: {self.users_root}")
    
    def get_user_shard(self, user_id: str) -> str:
        """
        Calculate shard for a user_id.
        
        Args:
            user_id: User ID
            
        Returns:
            str: Shard name (e.g., "shard_0000")
        """
        return get_user_shard(user_id, self.dev_mode)
    
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
        
        Creates:
        - users/{shard}/{user_id}/
        - users/{shard}/{user_id}/identity/
        - users/{shard}/{user_id}/scan_results/
        - users/{shard}/{user_id}/logs/
        - users/{shard}/{user_id}/preferences/
        
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
        
        logger.info(f"Created user directory: {user_dir}")
        return user_dir
    
    def user_directory_exists(self, user_id: str) -> bool:
        """
        Check if user directory exists and has required structure.
        
        Args:
            user_id: User ID
            
        Returns:
            bool: True if user directory exists with identity/profile.json
        """
        user_path = self.get_user_path(user_id)
        profile_path = user_path / "identity" / "profile.json"
        return user_path.exists() and profile_path.exists()
    
    def get_shard_path(self, shard: str) -> Path:
        """
        Get path to a specific shard directory.
        
        Args:
            shard: Shard name (e.g., "shard_0000")
            
        Returns:
            Path: Path to shard directory
        """
        return self.users_root / shard
    
    def ensure_shard_exists(self, shard: str):
        """
        Ensure a shard directory exists.
        
        Args:
            shard: Shard name (e.g., "shard_0000")
        """
        shard_path = self.get_shard_path(shard)
        shard_path.mkdir(parents=True, exist_ok=True)
    
    def list_users_in_shard(self, shard: str) -> list:
        """
        List all user IDs in a specific shard.
        
        Args:
            shard: Shard name (e.g., "shard_0000")
            
        Returns:
            list: List of user IDs in the shard
        """
        shard_path = self.get_shard_path(shard)
        if not shard_path.exists():
            return []
        
        user_ids = []
        for item in shard_path.iterdir():
            if item.is_dir() and (item / "identity" / "profile.json").exists():
                user_ids.append(item.name)
        
        return user_ids
    
    def get_shard_count(self) -> int:
        """
        Get the number of shards that currently exist.
        
        Returns:
            int: Number of shard directories
        """
        if not self.users_root.exists():
            return 0
        
        count = 0
        for item in self.users_root.iterdir():
            if item.is_dir() and item.name.startswith("shard_"):
                count += 1
        
        return count

