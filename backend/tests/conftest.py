import os
import shutil
import tempfile
import pytest
import kuzu


@pytest.fixture
def tmp_kuzu_db():
    """Create a temporary Kuzu database for testing."""
    tmp_dir = tempfile.mkdtemp(prefix="kuzu_test_")
    db = kuzu.Database(tmp_dir)
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
    yield tmp_dir, db, conn
    shutil.rmtree(tmp_dir, ignore_errors=True)
