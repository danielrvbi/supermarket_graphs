"""
Shared SQLite plumbing for stage tables.

Every stage reads/writes its own table in processed/processed_data.db.
Each stage defines a store subclass with its own SCHEMA.
"""

import sqlite3
from pathlib import Path


class SQLiteStore:
    """Base class: owns the db path, connection and schema creation."""

    SCHEMA = ""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        """Get database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_schema(self):
        """Create database and table if not exists."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        conn.executescript(self.SCHEMA)
        conn.close()
