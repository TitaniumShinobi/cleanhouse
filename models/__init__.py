# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - models/__init__.py
#  Database models and schemas
#  Devon • 2025‑01‑27
# ──────────────────────────────────────────────────────────────────────────────

from .user_model import User, UserService
from .database import DatabaseManager
from .user_registry import UserRegistry, generate_user_id, generate_user_id_from_existing, normalize_email_for_user_id
from .shard_manager import ShardManager, get_user_shard, SHARD_COUNT, SHARD_PADDING

__all__ = [
    'User', 
    'UserService', 
    'DatabaseManager',
    'UserRegistry',
    'ShardManager',
    'generate_user_id',
    'generate_user_id_from_existing',
    'normalize_email_for_user_id',
    'get_user_shard',
    'SHARD_COUNT',
    'SHARD_PADDING'
]
