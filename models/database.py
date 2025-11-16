# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - models/database.py
#  Database management and connection handling
#  Devon • 2025‑01‑27
# ──────────────────────────────────────────────────────────────────────────────

import sqlite3
import logging
from pathlib import Path
from typing import Optional
import os
import threading

class DatabaseManager:
    """
    Manages database connections and schema initialization.
    Uses SQLite for development, can be extended for PostgreSQL in production.
    Thread-safe: Each thread gets its own connection.
    """
    
    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize database manager.
        
        Args:
            db_path: Path to database file. If None, uses default location.
        """
        if db_path is None:
            # Default to user's home directory for CleanHouse data
            home_dir = Path.home()
            cleanhouse_dir = home_dir / ".cleanhouse"
            cleanhouse_dir.mkdir(exist_ok=True)
            db_path = str(cleanhouse_dir / "cleanhouse.db")
        
        self.db_path = db_path
        # Thread-local storage for connections (SQLite is thread-local)
        self._local = threading.local()
        
        # Initialize database schema (only once, using main thread connection)
        self._initialize_database()
    
    def _initialize_database(self):
        """Initialize database with required tables."""
        try:
            # Create a temporary connection just for schema initialization
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            
            # Create users table
            self._create_users_table(conn)
            
            conn.close()
            logging.info(f"Database initialized at: {self.db_path}")
            
        except Exception as e:
            logging.error(f"Database initialization failed: {e}")
            raise
    
    def _create_users_table(self, conn):
        """Create users table with proper schema."""
        cursor = conn.cursor()
        
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT 1,
            last_login TIMESTAMP NULL
        )
        """
        
        cursor.execute(create_table_sql)
        
        # Create index on email for faster lookups
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
        
        conn.commit()
        logging.info("Users table created successfully")
    
    def get_connection(self):
        """Get database connection for current thread."""
        # Use thread-local storage - each thread gets its own connection
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            self._local.connection = sqlite3.connect(self.db_path, check_same_thread=False)
            self._local.connection.row_factory = sqlite3.Row
        return self._local.connection
    
    def close_connection(self):
        """Close database connection for current thread."""
        if hasattr(self._local, 'connection') and self._local.connection:
            self._local.connection.close()
            self._local.connection = None
    
    def __enter__(self):
        """Context manager entry."""
        return self.get_connection()
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - don't close, keep connection for thread."""
        # Don't close connection here - let it persist for the thread
        # Connection will be closed when thread ends or explicitly closed
        pass
    
    def __del__(self):
        """Destructor to ensure connection is closed."""
        self.close_connection()
