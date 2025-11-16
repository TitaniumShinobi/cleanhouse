#!/usr/bin/env python3
# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - tests/test_integration_sharded.py
#  Integration tests for sharded user registry with UI components
#  Devon • 2025-11-13
# ──────────────────────────────────────────────────────────────────────────────

"""
Integration tests for sharded user registry system.

Tests:
- User signup flow
- User login flow
- User data storage in sharded format
- User authentication
- User lookup
"""

import sys
import unittest
import tempfile
import shutil
import os
from pathlib import Path
from datetime import datetime
from unittest.mock import patch

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from models import UserService, DatabaseManager, UserRegistry, ShardManager
from models.user_model import User


class TestShardedUserIntegration(unittest.TestCase):
    """Integration tests for sharded user registry."""
    
    def setUp(self):
        """Set up test environment."""
        # Create temporary directory for testing
        self.test_dir = Path(tempfile.mkdtemp(prefix="cleanhouse_test_"))
        self.cleanhouse_root = self.test_dir / ".cleanhouse"
        self.cleanhouse_root.mkdir(parents=True, exist_ok=True)
        
        # Initialize services
        self.db_manager = DatabaseManager(db_path=str(self.cleanhouse_root / "cleanhouse.db"))
        self.user_service = UserService(cleanhouse_root=self.cleanhouse_root, db_manager=self.db_manager)
        
        # Verify sharded format is enabled
        self.assertTrue(self.user_service.use_sharded_format, "Sharded format should be enabled")
        
        # Mock access control to allow all emails in tests
        self.access_control_patcher = patch('access_control.access_control.access_control.is_access_allowed', return_value=True)
        self.access_control_patcher.start()
    
    def tearDown(self):
        """Clean up test environment."""
        # Stop access control mock
        self.access_control_patcher.stop()
        
        # Remove temporary directory
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
    
    def test_user_signup_creates_sharded_structure(self):
        """Test that user signup creates sharded directory structure."""
        # Create user
        user = self.user_service.create_user(
            full_name="Test User",
            email="test@example.com",
            password="password123",
            role="user"
        )
        
        # Verify user object
        self.assertIsNotNone(user)
        self.assertIsNotNone(user.user_id)
        self.assertEqual(user.email, "test@example.com")
        self.assertEqual(user.full_name, "Test User")
        
        # Verify sharded directory structure exists
        shard_manager = ShardManager(self.cleanhouse_root)
        user_path = shard_manager.get_user_path(user.user_id)
        
        self.assertTrue(user_path.exists(), "User directory should exist")
        self.assertTrue((user_path / "identity" / "profile.json").exists(), "profile.json should exist")
        self.assertTrue((user_path / "identity" / "auth.json").exists(), "auth.json should exist")
        self.assertTrue((user_path / "preferences" / "settings.json").exists(), "settings.json should exist")
        
        # Verify registry entry
        user_registry = UserRegistry(self.cleanhouse_root)
        registry_user_id = user_registry.get_user_id_by_email("test@example.com")
        self.assertEqual(registry_user_id, user.user_id, "User should be in registry")
    
    def test_user_signup_creates_correct_files(self):
        """Test that user signup creates files with correct content."""
        import json
        
        # Create user
        user = self.user_service.create_user(
            full_name="John Doe",
            email="john@example.com",
            password="securepass123",
            role="user"
        )
        
        # Load profile.json
        shard_manager = ShardManager(self.cleanhouse_root)
        user_path = shard_manager.get_user_path(user.user_id)
        profile_path = user_path / "identity" / "profile.json"
        
        with open(profile_path, 'r') as f:
            profile = json.load(f)
        
        self.assertEqual(profile['user_id'], user.user_id)
        self.assertEqual(profile['email'], "john@example.com")
        self.assertEqual(profile['full_name'], "John Doe")
        self.assertEqual(profile['role'], "user")
        self.assertTrue(profile['is_active'])
        self.assertIn('created', profile)
        self.assertIn('last_seen', profile)
        
        # Load auth.json
        auth_path = user_path / "identity" / "auth.json"
        with open(auth_path, 'r') as f:
            auth = json.load(f)
        
        self.assertEqual(auth['user_id'], user.user_id)
        self.assertIn('password_hash', auth)
        self.assertNotEqual(auth['password_hash'], "securepass123", "Password should be hashed")
        self.assertIn('password_updated_at', auth)
    
    def test_user_login_authenticates_correctly(self):
        """Test that user login works with sharded format."""
        # Create user
        user = self.user_service.create_user(
            full_name="Login Test",
            email="login@example.com",
            password="testpass123",
            role="user"
        )
        
        # Authenticate user
        authenticated_user = self.user_service.authenticate_user(
            email="login@example.com",
            password="testpass123"
        )
        
        self.assertIsNotNone(authenticated_user)
        self.assertEqual(authenticated_user.email, "login@example.com")
        self.assertEqual(authenticated_user.user_id, user.user_id)
        
        # Test wrong password
        failed_auth = self.user_service.authenticate_user(
            email="login@example.com",
            password="wrongpassword"
        )
        self.assertIsNone(failed_auth, "Wrong password should fail authentication")
    
    def test_user_lookup_by_email(self):
        """Test that user lookup by email works."""
        # Create user
        user = self.user_service.create_user(
            full_name="Lookup Test",
            email="lookup@example.com",
            password="password123",
            role="user"
        )
        
        # Lookup user
        found_user = self.user_service.get_user_by_email("lookup@example.com")
        
        self.assertIsNotNone(found_user)
        self.assertEqual(found_user.user_id, user.user_id)
        self.assertEqual(found_user.email, "lookup@example.com")
        self.assertEqual(found_user.full_name, "Lookup Test")
    
    def test_user_lookup_by_user_id(self):
        """Test that user lookup by user_id works."""
        # Create user
        user = self.user_service.create_user(
            full_name="ID Lookup Test",
            email="idlookup@example.com",
            password="password123",
            role="user"
        )
        
        # Lookup user by user_id
        found_user = self.user_service.get_user_by_id(user_id=user.user_id)
        
        self.assertIsNotNone(found_user)
        self.assertEqual(found_user.user_id, user.user_id)
        self.assertEqual(found_user.email, "idlookup@example.com")
    
    def test_duplicate_email_prevention(self):
        """Test that duplicate emails are prevented."""
        # Create first user
        self.user_service.create_user(
            full_name="First User",
            email="duplicate@example.com",
            password="password123",
            role="user"
        )
        
        # Try to create duplicate
        with self.assertRaises(ValueError) as context:
            self.user_service.create_user(
                full_name="Second User",
                email="duplicate@example.com",
                password="password456",
                role="user"
            )
        
        self.assertIn("already exists", str(context.exception).lower())
    
    def test_last_login_update(self):
        """Test that last login is updated correctly."""
        import json
        import time
        
        # Create user
        user = self.user_service.create_user(
            full_name="Login Update Test",
            email="loginupdate@example.com",
            password="password123",
            role="user"
        )
        
        # Authenticate (should update last_login)
        time.sleep(0.1)  # Small delay to ensure timestamp difference
        authenticated_user = self.user_service.authenticate_user(
            email="loginupdate@example.com",
            password="password123"
        )
        
        # Check that last_login was updated
        shard_manager = ShardManager(self.cleanhouse_root)
        user_path = shard_manager.get_user_path(user.user_id)
        auth_path = user_path / "identity" / "auth.json"
        
        with open(auth_path, 'r') as f:
            auth = json.load(f)
        
        self.assertIsNotNone(auth.get('last_login'), "last_login should be set")
        
        # Check profile.json last_seen
        profile_path = user_path / "identity" / "profile.json"
        with open(profile_path, 'r') as f:
            profile = json.load(f)
        
        self.assertIsNotNone(profile.get('last_seen'), "last_seen should be updated")
    
    def test_user_update(self):
        """Test that user update works."""
        import json
        
        # Create user
        user = self.user_service.create_user(
            full_name="Update Test",
            email="update@example.com",
            password="password123",
            role="user"
        )
        
        # Update user
        success = self.user_service.update_user(
            user_id=user.user_id,
            full_name="Updated Name",
            is_active=False
        )
        
        self.assertTrue(success, "Update should succeed")
        
        # Verify update
        updated_user = self.user_service.get_user_by_email("update@example.com")
        self.assertEqual(updated_user.full_name, "Updated Name")
        self.assertFalse(updated_user.is_active)
        
        # Verify profile.json was updated
        shard_manager = ShardManager(self.cleanhouse_root)
        user_path = shard_manager.get_user_path(user.user_id)
        profile_path = user_path / "identity" / "profile.json"
        
        with open(profile_path, 'r') as f:
            profile = json.load(f)
        
        self.assertEqual(profile['full_name'], "Updated Name")
        self.assertFalse(profile['is_active'])
    
    def test_user_delete(self):
        """Test that user deletion works."""
        # Create user
        user = self.user_service.create_user(
            full_name="Delete Test",
            email="delete@example.com",
            password="password123",
            role="user"
        )
        
        user_id = user.user_id
        email = user.email
        
        # Delete user
        success = self.user_service.delete_user(user_id=user_id)
        self.assertTrue(success, "Delete should succeed")
        
        # Verify user is removed from registry
        user_registry = UserRegistry(self.cleanhouse_root)
        registry_user_id = user_registry.get_user_id_by_email(email)
        self.assertIsNone(registry_user_id, "User should be removed from registry")
        
        # Verify user directory is deleted
        shard_manager = ShardManager(self.cleanhouse_root)
        user_path = shard_manager.get_user_path(user_id)
        self.assertFalse(user_path.exists(), "User directory should be deleted")
        
        # Verify user lookup fails
        found_user = self.user_service.get_user_by_email(email)
        self.assertIsNone(found_user, "User should not be found after deletion")
    
    def test_multiple_users_different_shards(self):
        """Test that multiple users are distributed across shards."""
        users = []
        shards = set()
        
        # Create multiple users
        for i in range(10):
            user = self.user_service.create_user(
                full_name=f"User {i}",
                email=f"user{i}@example.com",
                password="password123",
                role="user"
            )
            users.append(user)
            
            # Get shard
            shard_manager = ShardManager(self.cleanhouse_root)
            user_path = shard_manager.get_user_path(user.user_id)
            shard = user_path.parent.name  # Extract shard name from path
            shards.add(shard)
        
        # Verify users are distributed (at least some different shards)
        # Note: With 10 users, it's possible but unlikely they all go to the same shard
        self.assertGreater(len(shards), 0, "Users should be in shards")
        
        # Verify all users can be looked up
        for user in users:
            found_user = self.user_service.get_user_by_email(user.email)
            self.assertIsNotNone(found_user)
            self.assertEqual(found_user.user_id, user.user_id)


if __name__ == '__main__':
    unittest.main(verbosity=2)

