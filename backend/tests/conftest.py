import os
import shutil
import tempfile
import pytest
import kuzu


@pytest.fixture
def tmp_kuzu_db():
    """Create a temporary Kuzu database for testing."""
    # Kuzu >= 0.11 requires that the database path does NOT already exist
    # as a directory. Use a subdirectory name inside a temp dir.
    parent = tempfile.mkdtemp(prefix="kuzu_test_parent_")
    db_path = os.path.join(parent, "db")
    db = kuzu.Database(db_path)
    conn = kuzu.Connection(db)
    # Create schema
    conn.execute("""
        CREATE NODE TABLE Entity (
            uuid STRING PRIMARY KEY,
            graph_id STRING,
            name STRING,
            label STRING,
            summary STRING,
            attributes STRING
        )
    """)
    conn.execute("""
        CREATE REL TABLE RELATES_TO (
            FROM Entity TO Entity,
            relation STRING,
            fact STRING,
            graph_id STRING,
            created_at STRING
        )
    """)
    yield db_path, db, conn
    shutil.rmtree(parent, ignore_errors=True)
