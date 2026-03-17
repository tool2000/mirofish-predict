"""
LocalGraphMemoryUpdater unit tests.
Verifies activity recording, DO_NOTHING skipping, and manager singleton pattern.
"""

import time
import json
import pytest
import importlib
import threading

# Import directly from the module file to avoid app.services.__init__.py
# which may pull in zep_cloud (not installed in test env).
_spec = importlib.util.spec_from_file_location(
    "local_graph_memory_updater",
    str(
        __import__("pathlib").Path(__file__).resolve().parent.parent
        / "app"
        / "services"
        / "local_graph_memory_updater.py"
    ),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

AgentActivity = _mod.AgentActivity
LocalGraphMemoryUpdater = _mod.LocalGraphMemoryUpdater
LocalGraphMemoryManager = _mod.LocalGraphMemoryManager

# Also need LocalGraphService for integration tests
_svc_spec = importlib.util.spec_from_file_location(
    "local_graph_service",
    str(
        __import__("pathlib").Path(__file__).resolve().parent.parent
        / "app"
        / "services"
        / "local_graph_service.py"
    ),
)
_svc_mod = importlib.util.module_from_spec(_svc_spec)
_svc_spec.loader.exec_module(_svc_mod)
LocalGraphService = _svc_mod.LocalGraphService


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _make_service(tmp_dir):
    """Create a LocalGraphService for testing (no LLM used)."""
    return LocalGraphService(
        db_dir=tmp_dir,
        llm_base_url="http://localhost:8080/v1",
        llm_api_key="test-key",
        llm_model="openai/test-model",
    )


def _make_activity(action_type="CREATE_POST", agent_id=1, agent_name="TestAgent",
                   platform="twitter", round_num=1, **extra_args):
    """Create a test AgentActivity."""
    return AgentActivity(
        platform=platform,
        agent_id=agent_id,
        agent_name=agent_name,
        action_type=action_type,
        action_args=extra_args,
        round_num=round_num,
        timestamp="2025-01-01T00:00:00",
    )


# ------------------------------------------------------------------
# AgentActivity tests
# ------------------------------------------------------------------


class TestAgentActivity:
    """AgentActivity dataclass tests."""

    def test_to_episode_text_create_post(self):
        act = _make_activity("CREATE_POST", content="Hello world")
        text = act.to_episode_text()
        assert "TestAgent" in text
        assert "Hello world" in text

    def test_to_episode_text_like_post(self):
        act = _make_activity("LIKE_POST", post_author_name="Alice", post_content="Great post")
        text = act.to_episode_text()
        assert "Alice" in text
        assert "Great post" in text

    def test_to_episode_text_generic(self):
        act = _make_activity("UNKNOWN_TYPE")
        text = act.to_episode_text()
        assert "UNKNOWN_TYPE" in text


# ------------------------------------------------------------------
# LocalGraphMemoryUpdater tests
# ------------------------------------------------------------------


class TestLocalGraphMemoryUpdater:
    """Updater core behaviour tests."""

    def test_do_nothing_is_skipped(self, tmp_kuzu_db):
        """DO_NOTHING activities are counted as skipped and not queued."""
        tmp_dir, db, conn = tmp_kuzu_db
        svc = _make_service(tmp_dir)
        updater = LocalGraphMemoryUpdater("test-graph", svc)

        activity = _make_activity("DO_NOTHING")
        updater.add_activity(activity)

        assert updater._skipped_count == 1
        assert updater._total_activities == 0
        assert updater._activity_queue.qsize() == 0

    def test_create_post_is_queued(self, tmp_kuzu_db):
        """CREATE_POST activity is accepted and queued."""
        tmp_dir, db, conn = tmp_kuzu_db
        svc = _make_service(tmp_dir)
        updater = LocalGraphMemoryUpdater("test-graph", svc)

        activity = _make_activity("CREATE_POST", content="Test post")
        updater.add_activity(activity)

        assert updater._total_activities == 1
        assert updater._skipped_count == 0
        assert updater._activity_queue.qsize() == 1

    def test_search_actions_skipped_in_graph(self, tmp_kuzu_db):
        """SEARCH_POSTS actions are queued but produce no graph edge."""
        tmp_dir, db, conn = tmp_kuzu_db
        svc = _make_service(tmp_dir)
        updater = LocalGraphMemoryUpdater("test-graph", svc)
        updater.start()

        activity = _make_activity("SEARCH_POSTS", query="test query")
        updater.add_activity(activity)

        # Wait for worker to process
        time.sleep(1)
        updater.stop()

        # Activity was counted but no edges created (SEARCH_POSTS not in relation map)
        assert updater._total_activities == 1
        edges = svc.get_all_edges("test-graph")
        assert len(edges) == 0

    def test_create_post_inserts_edge(self, tmp_kuzu_db):
        """CREATE_POST activity inserts an entity node and a RELATES_TO edge."""
        tmp_dir, db, conn = tmp_kuzu_db
        svc = _make_service(tmp_dir)
        updater = LocalGraphMemoryUpdater("test-graph", svc)
        updater.start()

        # Add enough activities to trigger a batch (BATCH_SIZE = 5)
        for i in range(5):
            activity = _make_activity(
                "CREATE_POST",
                agent_id=1,
                agent_name="Agent1",
                round_num=i + 1,
                content=f"Post {i + 1}",
            )
            updater.add_activity(activity)

        # Wait for the worker to process the batch
        time.sleep(2)
        updater.stop()

        # Check stats
        assert updater._total_activities == 5
        assert updater._total_sent >= 1
        assert updater._total_items_sent >= 5

        # Check graph data
        edges = svc.get_all_edges("test-graph")
        assert len(edges) == 5
        for edge in edges:
            assert edge["name"] == "POSTED"

        # Agent node should exist
        nodes = svc.get_all_nodes("test-graph")
        agent_nodes = [n for n in nodes if n["name"] == "Agent1"]
        assert len(agent_nodes) == 1

    def test_add_activity_from_dict(self, tmp_kuzu_db):
        """add_activity_from_dict correctly constructs and queues an activity."""
        tmp_dir, db, conn = tmp_kuzu_db
        svc = _make_service(tmp_dir)
        updater = LocalGraphMemoryUpdater("test-graph", svc)

        data = {
            "agent_id": 42,
            "agent_name": "DictAgent",
            "action_type": "FOLLOW",
            "action_args": {"target_user_name": "Bob"},
            "round": 3,
            "timestamp": "2025-06-01T12:00:00",
        }
        updater.add_activity_from_dict(data, "twitter")

        assert updater._total_activities == 1
        assert updater._activity_queue.qsize() == 1

    def test_add_activity_from_dict_skips_events(self, tmp_kuzu_db):
        """Event-type entries (with event_type key) are silently skipped."""
        tmp_dir, db, conn = tmp_kuzu_db
        svc = _make_service(tmp_dir)
        updater = LocalGraphMemoryUpdater("test-graph", svc)

        data = {"event_type": "round_start", "round": 1}
        updater.add_activity_from_dict(data, "twitter")

        assert updater._total_activities == 0

    def test_get_stats(self, tmp_kuzu_db):
        """get_stats returns a dict with all expected keys."""
        tmp_dir, db, conn = tmp_kuzu_db
        svc = _make_service(tmp_dir)
        updater = LocalGraphMemoryUpdater("test-graph", svc)

        stats = updater.get_stats()
        expected_keys = {
            "graph_id", "batch_size", "total_activities", "batches_sent",
            "items_sent", "failed_count", "skipped_count", "queue_size",
            "buffer_sizes", "running",
        }
        assert set(stats.keys()) == expected_keys
        assert stats["graph_id"] == "test-graph"
        assert stats["batch_size"] == 5

    def test_mixed_action_types(self, tmp_kuzu_db):
        """Different action types produce correct relation names."""
        tmp_dir, db, conn = tmp_kuzu_db
        svc = _make_service(tmp_dir)
        updater = LocalGraphMemoryUpdater("test-graph", svc)
        updater.start()

        actions = [
            ("CREATE_POST", "POSTED"),
            ("LIKE_POST", "REACTED"),
            ("REPOST", "SHARED"),
            ("FOLLOW", "SOCIAL"),
            ("CREATE_COMMENT", "COMMENTED"),
        ]
        for i, (action_type, _) in enumerate(actions):
            activity = _make_activity(
                action_type,
                agent_id=i + 10,
                agent_name=f"Agent{i + 10}",
                round_num=1,
                content=f"test {action_type}",
            )
            updater.add_activity(activity)

        # Wait for processing (5 activities = 1 batch)
        time.sleep(2)
        updater.stop()

        edges = svc.get_all_edges("test-graph")
        edge_relations = {e["name"] for e in edges}
        assert "POSTED" in edge_relations
        assert "REACTED" in edge_relations
        assert "SHARED" in edge_relations
        assert "SOCIAL" in edge_relations
        assert "COMMENTED" in edge_relations


# ------------------------------------------------------------------
# LocalGraphMemoryManager tests
# ------------------------------------------------------------------


class TestLocalGraphMemoryManager:
    """Singleton manager pattern tests."""

    def setup_method(self):
        """Reset manager state before each test."""
        LocalGraphMemoryManager._updaters = {}
        LocalGraphMemoryManager._stop_all_done = False

    def test_create_and_get_updater(self, tmp_kuzu_db):
        """create_updater returns a running updater; get_updater retrieves it."""
        tmp_dir, db, conn = tmp_kuzu_db
        svc = _make_service(tmp_dir)

        updater = LocalGraphMemoryManager.create_updater("sim-1", "graph-1", graph_service=svc)
        assert updater is not None
        assert updater._running is True

        retrieved = LocalGraphMemoryManager.get_updater("sim-1")
        assert retrieved is updater

        LocalGraphMemoryManager.stop_updater("sim-1")
        assert LocalGraphMemoryManager.get_updater("sim-1") is None

    def test_create_replaces_existing(self, tmp_kuzu_db):
        """Creating an updater for the same simulation_id stops the old one."""
        tmp_dir, db, conn = tmp_kuzu_db
        svc = _make_service(tmp_dir)

        updater1 = LocalGraphMemoryManager.create_updater("sim-1", "graph-1", graph_service=svc)
        updater2 = LocalGraphMemoryManager.create_updater("sim-1", "graph-2", graph_service=svc)

        assert updater1._running is False  # old updater was stopped
        assert updater2._running is True
        assert LocalGraphMemoryManager.get_updater("sim-1") is updater2

        LocalGraphMemoryManager.stop_updater("sim-1")

    def test_stop_all(self, tmp_kuzu_db):
        """stop_all stops all updaters and clears the registry."""
        tmp_dir, db, conn = tmp_kuzu_db
        svc = _make_service(tmp_dir)

        LocalGraphMemoryManager.create_updater("sim-1", "graph-1", graph_service=svc)
        LocalGraphMemoryManager.create_updater("sim-2", "graph-2", graph_service=svc)

        LocalGraphMemoryManager.stop_all()

        assert len(LocalGraphMemoryManager._updaters) == 0

    def test_stop_all_idempotent(self, tmp_kuzu_db):
        """Calling stop_all multiple times does not raise."""
        tmp_dir, db, conn = tmp_kuzu_db
        svc = _make_service(tmp_dir)

        LocalGraphMemoryManager.create_updater("sim-1", "graph-1", graph_service=svc)
        LocalGraphMemoryManager.stop_all()
        LocalGraphMemoryManager.stop_all()  # Should not raise

    def test_get_all_stats(self, tmp_kuzu_db):
        """get_all_stats returns stats for all registered updaters."""
        tmp_dir, db, conn = tmp_kuzu_db
        svc = _make_service(tmp_dir)

        LocalGraphMemoryManager.create_updater("sim-1", "graph-1", graph_service=svc)
        LocalGraphMemoryManager.create_updater("sim-2", "graph-2", graph_service=svc)

        all_stats = LocalGraphMemoryManager.get_all_stats()
        assert "sim-1" in all_stats
        assert "sim-2" in all_stats
        assert all_stats["sim-1"]["graph_id"] == "graph-1"
        assert all_stats["sim-2"]["graph_id"] == "graph-2"

        LocalGraphMemoryManager.stop_all()

    def test_stop_nonexistent_updater(self):
        """Stopping a non-existent updater does not raise."""
        LocalGraphMemoryManager.stop_updater("nonexistent-sim")
