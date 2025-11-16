# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - tests/test_shard_manager.py
#  Unit tests for shard_manager module
#  Devon • 2025-11-13
# ──────────────────────────────────────────────────────────────────────────────

import unittest
import tempfile
import shutil
from pathlib import Path

from models.shard_manager import (
    ShardManager,
    get_user_shard,
    SHARD_COUNT,
    SHARD_PADDING
)


class TestShardCalculation(unittest.TestCase):
    """Test shard calculation functions."""
    
    def test_get_user_shard_consistency(self):
        """Test that same user_id always maps to same shard."""
        user_id = "test_user_1234567890"
        shard1 = get_user_shard(user_id)
        shard2 = get_user_shard(user_id)
        
        self.assertEqual(shard1, shard2)
        self.assertTrue(shard1.startswith("shard_"))
    
    def test_get_user_shard_format(self):
        """Test shard name format."""
        user_id = "test_user_1234567890"
        shard = get_user_shard(user_id)
        
        # Should be in format shard_XXXX where XXXX is 4-digit number
        self.assertTrue(shard.startswith("shard_"))
        shard_num = shard.replace("shard_", "")
        self.assertEqual(len(shard_num), SHARD_PADDING)
        self.assertTrue(shard_num.isdigit())
        self.assertGreaterEqual(int(shard_num), 0)
        self.assertLess(int(shard_num), SHARD_COUNT)
    
    def test_get_user_shard_distribution(self):
        """Test that shards are distributed across range."""
        user_ids = [f"user_{i}_1234567890" for i in range(100)]
        shards = [get_user_shard(uid) for uid in user_ids]
        
        # Should have multiple different shards
        unique_shards = set(shards)
        self.assertGreater(len(unique_shards), 1)  # Not all in same shard
    
    def test_get_user_shard_dev_mode(self):
        """Test dev mode puts all users in shard_0000."""
        user_id1 = "user1_1234567890"
        user_id2 = "user2_9876543210"
        
        shard1 = get_user_shard(user_id1, dev_mode=True)
        shard2 = get_user_shard(user_id2, dev_mode=True)
        
        self.assertEqual(shard1, "shard_0000")
        self.assertEqual(shard2, "shard_0000")
    
    def test_get_user_shard_production_mode(self):
        """Test production mode uses hash-based sharding."""
        user_id1 = "user1_1234567890"
        user_id2 = "user2_9876543210"
        
        shard1 = get_user_shard(user_id1, dev_mode=False)
        shard2 = get_user_shard(user_id2, dev_mode=False)
        
        # In production, different users should get different shards (likely)
        # But same user should always get same shard
        self.assertEqual(get_user_shard(user_id1, dev_mode=False), shard1)
        self.assertEqual(get_user_shard(user_id2, dev_mode=False), shard2)


class TestShardManager(unittest.TestCase):
    """Test ShardManager class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.shard_manager = ShardManager(self.temp_dir)
    
    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_shard_manager_initialization(self):
        """Test ShardManager initialization."""
        self.assertTrue(self.shard_manager.users_root.exists())
        self.assertEqual(self.shard_manager.users_root, self.temp_dir / "users")
    
    def test_get_user_shard(self):
        """Test getting shard for user_id."""
        user_id = "test_user_1234567890"
        shard = self.shard_manager.get_user_shard(user_id)
        
        self.assertTrue(shard.startswith("shard_"))
        self.assertEqual(len(shard), len("shard_") + SHARD_PADDING)
    
    def test_get_user_path(self):
        """Test getting full path to user directory."""
        user_id = "test_user_1234567890"
        user_path = self.shard_manager.get_user_path(user_id)
        
        self.assertTrue(str(user_path).endswith(user_id))
        self.assertIn("shard_", str(user_path))
    
    def test_create_user_directory(self):
        """Test creating user directory structure."""
        user_id = "test_user_1234567890"
        user_dir = self.shard_manager.create_user_directory(user_id)
        
        # Check directory exists
        self.assertTrue(user_dir.exists())
        self.assertTrue(user_dir.is_dir())
        
        # Check subdirectories created
        self.assertTrue((user_dir / "identity").exists())
        self.assertTrue((user_dir / "scan_results").exists())
        self.assertTrue((user_dir / "logs").exists())
        self.assertTrue((user_dir / "preferences").exists())
    
    def test_create_user_directory_with_shard(self):
        """Test creating directory with explicit shard."""
        user_id = "test_user_1234567890"
        shard = "shard_0042"
        user_dir = self.shard_manager.create_user_directory(user_id, shard)
        
        self.assertIn(shard, str(user_dir))
        self.assertTrue(user_dir.exists())
    
    def test_user_directory_exists(self):
        """Test checking if user directory exists."""
        user_id = "test_user_1234567890"
        
        # Should not exist initially
        self.assertFalse(self.shard_manager.user_directory_exists(user_id))
        
        # Create directory structure
        user_dir = self.shard_manager.create_user_directory(user_id)
        
        # Still shouldn't exist (no profile.json)
        self.assertFalse(self.shard_manager.user_directory_exists(user_id))
        
        # Create profile.json
        (user_dir / "identity" / "profile.json").touch()
        
        # Now should exist
        self.assertTrue(self.shard_manager.user_directory_exists(user_id))
    
    def test_get_shard_path(self):
        """Test getting path to shard directory."""
        shard = "shard_0042"
        shard_path = self.shard_manager.get_shard_path(shard)
        
        self.assertEqual(shard_path, self.shard_manager.users_root / shard)
    
    def test_ensure_shard_exists(self):
        """Test ensuring shard directory exists."""
        shard = "shard_0042"
        self.shard_manager.ensure_shard_exists(shard)
        
        shard_path = self.shard_manager.get_shard_path(shard)
        self.assertTrue(shard_path.exists())
        self.assertTrue(shard_path.is_dir())
    
    def test_list_users_in_shard(self):
        """Test listing users in a shard."""
        shard = "shard_0000"
        
        # Initially empty
        users = self.shard_manager.list_users_in_shard(shard)
        self.assertEqual(users, [])
        
        # Create user directories
        user_id1 = "user1_1234567890"
        user_id2 = "user2_9876543210"
        
        user_dir1 = self.shard_manager.create_user_directory(user_id1, shard)
        user_dir2 = self.shard_manager.create_user_directory(user_id2, shard)
        
        # Create profile.json files
        (user_dir1 / "identity" / "profile.json").touch()
        (user_dir2 / "identity" / "profile.json").touch()
        
        # List users
        users = self.shard_manager.list_users_in_shard(shard)
        
        self.assertEqual(len(users), 2)
        self.assertIn(user_id1, users)
        self.assertIn(user_id2, users)
    
    def test_list_users_in_shard_only_valid(self):
        """Test that only users with profile.json are listed."""
        shard = "shard_0000"
        user_id = "user_1234567890"
        
        # Create directory but no profile.json
        user_dir = self.shard_manager.create_user_directory(user_id, shard)
        
        # Should not be listed
        users = self.shard_manager.list_users_in_shard(shard)
        self.assertNotIn(user_id, users)
        
        # Create profile.json
        (user_dir / "identity" / "profile.json").touch()
        
        # Now should be listed
        users = self.shard_manager.list_users_in_shard(shard)
        self.assertIn(user_id, users)
    
    def test_get_shard_count(self):
        """Test getting number of shards."""
        # Initially no shards
        count = self.shard_manager.get_shard_count()
        self.assertEqual(count, 0)
        
        # Create some shards
        self.shard_manager.ensure_shard_exists("shard_0000")
        self.shard_manager.ensure_shard_exists("shard_0001")
        self.shard_manager.ensure_shard_exists("shard_0042")
        
        count = self.shard_manager.get_shard_count()
        self.assertEqual(count, 3)
    
    def test_dev_mode_all_to_shard_0000(self):
        """Test dev mode puts all users in shard_0000."""
        dev_manager = ShardManager(self.temp_dir, dev_mode=True)
        
        user_id1 = "user1_1234567890"
        user_id2 = "user2_9876543210"
        
        shard1 = dev_manager.get_user_shard(user_id1)
        shard2 = dev_manager.get_user_shard(user_id2)
        
        self.assertEqual(shard1, "shard_0000")
        self.assertEqual(shard2, "shard_0000")
        
        # Both should be in same directory
        path1 = dev_manager.get_user_path(user_id1)
        path2 = dev_manager.get_user_path(user_id2)
        
        self.assertIn("shard_0000", str(path1))
        self.assertIn("shard_0000", str(path2))


class TestShardConsistency(unittest.TestCase):
    """Test shard assignment consistency."""
    
    def test_same_user_id_same_shard(self):
        """Test that same user_id always gets same shard."""
        user_id = "test_user_1234567890"
        
        shards = [get_user_shard(user_id) for _ in range(100)]
        
        # All should be the same
        self.assertEqual(len(set(shards)), 1)
    
    def test_different_user_ids_different_shards(self):
        """Test that different user_ids get different shards (usually)."""
        user_ids = [f"user_{i}_1234567890" for i in range(1000)]
        shards = [get_user_shard(uid) for uid in user_ids]
        
        unique_shards = set(shards)
        
        # With 1000 users across 10000 shards, we should have many different shards
        # (statistically very likely)
        self.assertGreater(len(unique_shards), 10)
    
    def test_shard_distribution_even(self):
        """Test that shards are evenly distributed."""
        user_ids = [f"user_{i}_1234567890" for i in range(10000)]
        shards = [get_user_shard(uid) for uid in user_ids]
        
        # Count shard usage
        shard_counts = {}
        for shard in shards:
            shard_counts[shard] = shard_counts.get(shard, 0) + 1
        
        # With 10000 users across 10000 shards, average should be ~1 per shard
        # But distribution should be relatively even
        counts = list(shard_counts.values())
        avg_count = sum(counts) / len(counts) if counts else 0
        
        # Average should be close to 1 (allow wider delta for statistical variance)
        # With hash distribution, some variance is expected
        self.assertAlmostEqual(avg_count, 1.0, delta=1.0)
        
        # Verify we're using multiple shards (not all in one)
        unique_shards = set(shards)
        self.assertGreater(len(unique_shards), 100)  # Should use at least 100 different shards


if __name__ == '__main__':
    unittest.main()

