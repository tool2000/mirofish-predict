"""
Local Kuzu graph memory updater.
Records simulation agent actions as RELATES_TO edges in the local Kuzu DB,
replacing the previous ZepGraphMemoryUpdater.
"""

import time
import threading
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime
from queue import Queue, Empty

try:
    from ..utils.logger import get_logger
    logger = get_logger('mirofish.local_graph_memory_updater')
except ImportError:
    import logging
    logger = logging.getLogger('mirofish.local_graph_memory_updater')


@dataclass
class AgentActivity:
    """Agent activity record."""
    platform: str           # twitter / reddit
    agent_id: int
    agent_name: str
    action_type: str        # CREATE_POST, LIKE_POST, etc.
    action_args: Dict[str, Any]
    round_num: int
    timestamp: str

    def to_episode_text(self) -> str:
        """
        Generate a human-readable description of the activity.
        """
        action_descriptions = {
            "CREATE_POST": self._describe_create_post,
            "LIKE_POST": self._describe_like_post,
            "DISLIKE_POST": self._describe_dislike_post,
            "REPOST": self._describe_repost,
            "QUOTE_POST": self._describe_quote_post,
            "FOLLOW": self._describe_follow,
            "CREATE_COMMENT": self._describe_create_comment,
            "LIKE_COMMENT": self._describe_like_comment,
            "DISLIKE_COMMENT": self._describe_dislike_comment,
            "SEARCH_POSTS": self._describe_search,
            "SEARCH_USER": self._describe_search_user,
            "MUTE": self._describe_mute,
        }

        describe_func = action_descriptions.get(self.action_type, self._describe_generic)
        description = describe_func()

        return f"{self.agent_name}: {description}"

    def _describe_create_post(self) -> str:
        content = self.action_args.get("content", "")
        if content:
            return f"게시글 '{content}'"
        return "게시글 작성"

    def _describe_like_post(self) -> str:
        post_content = self.action_args.get("post_content", "")
        post_author = self.action_args.get("post_author_name", "")

        if post_content and post_author:
            return f"{post_author}의 게시글 '{post_content}'"
        if post_content:
            return f"게시글 '{post_content}'"
        if post_author:
            return f"{post_author}의 게시글"
        return "게시글"

    def _describe_dislike_post(self) -> str:
        post_content = self.action_args.get("post_content", "")
        post_author = self.action_args.get("post_author_name", "")

        if post_content and post_author:
            return f"{post_author}의 게시글 '{post_content}'"
        if post_content:
            return f"게시글 '{post_content}'"
        if post_author:
            return f"{post_author}의 게시글"
        return "게시글"

    def _describe_repost(self) -> str:
        original_content = self.action_args.get("original_content", "")
        original_author = self.action_args.get("original_author_name", "")

        if original_content and original_author:
            return f"{original_author}의 원문 '{original_content}'"
        if original_content:
            return f"원문 '{original_content}'"
        if original_author:
            return f"{original_author}의 원문"
        return "원문"

    def _describe_quote_post(self) -> str:
        original_content = self.action_args.get("original_content", "")
        original_author = self.action_args.get("original_author_name", "")
        quote_content = self.action_args.get("quote_content", "") or self.action_args.get("content", "")

        base = ""
        if original_content and original_author:
            base = f"{original_author}의 원문 '{original_content}'"
        elif original_content:
            base = f"원문 '{original_content}'"
        elif original_author:
            base = f"{original_author}의 원문"
        else:
            base = "원문"

        if quote_content:
            base += f", 인용문 '{quote_content}'"
        return base

    def _describe_follow(self) -> str:
        target_user_name = self.action_args.get("target_user_name", "")

        if target_user_name:
            return f"사용자 '{target_user_name}'"
        return "사용자"

    def _describe_create_comment(self) -> str:
        content = self.action_args.get("content", "")
        post_content = self.action_args.get("post_content", "")
        post_author = self.action_args.get("post_author_name", "")

        if content:
            if post_content and post_author:
                return f"{post_author}의 게시글 '{post_content}'에 댓글 '{content}'"
            elif post_content:
                return f"게시글 '{post_content}'에 댓글 '{content}'"
            elif post_author:
                return f"{post_author}에게 댓글 '{content}'"
            return f"댓글 '{content}'"
        return "댓글 작성"

    def _describe_like_comment(self) -> str:
        comment_content = self.action_args.get("comment_content", "")
        comment_author = self.action_args.get("comment_author_name", "")

        if comment_content and comment_author:
            return f"{comment_author}의 댓글 '{comment_content}'"
        if comment_content:
            return f"댓글 '{comment_content}'"
        if comment_author:
            return f"{comment_author}의 댓글"
        return "댓글"

    def _describe_dislike_comment(self) -> str:
        comment_content = self.action_args.get("comment_content", "")
        comment_author = self.action_args.get("comment_author_name", "")

        if comment_content and comment_author:
            return f"{comment_author}의 댓글 '{comment_content}'"
        if comment_content:
            return f"댓글 '{comment_content}'"
        if comment_author:
            return f"{comment_author}의 댓글"
        return "댓글"

    def _describe_search(self) -> str:
        query = self.action_args.get("query", "") or self.action_args.get("keyword", "")
        return f"검색 '{query}'" if query else "검색"

    def _describe_search_user(self) -> str:
        query = self.action_args.get("query", "") or self.action_args.get("username", "")
        return f"검색 '{query}'" if query else "검색"

    def _describe_mute(self) -> str:
        target_user_name = self.action_args.get("target_user_name", "")

        if target_user_name:
            return f"사용자 '{target_user_name}'"
        return "사용자"

    def _describe_generic(self) -> str:
        return f"{self.action_type}"


# Action type -> RELATES_TO relation name mapping
_ACTION_RELATION_MAP: Dict[str, str] = {
    "CREATE_POST": "POSTED",
    "CREATE_COMMENT": "COMMENTED",
    "LIKE_POST": "REACTED",
    "DISLIKE_POST": "REACTED",
    "REPOST": "SHARED",
    "QUOTE_POST": "SHARED",
    "FOLLOW": "SOCIAL",
    "MUTE": "SOCIAL",
    "LIKE_COMMENT": "REACTED",
    "DISLIKE_COMMENT": "REACTED",
    # SEARCH_POSTS, SEARCH_USER -> no graph change (skipped)
}


class LocalGraphMemoryUpdater:
    """
    Records simulation actions as RELATES_TO edges in local Kuzu DB.

    Uses the same Queue + Lock + worker-thread pattern as ZepGraphMemoryUpdater,
    but writes directly to Kuzu instead of calling the Zep Cloud API.
    """

    BATCH_SIZE = 5
    SEND_INTERVAL = 0.1  # faster than Zep (local DB)

    PLATFORM_DISPLAY_NAMES = {
        'twitter': '1',
        'reddit': '2',
    }

    MAX_RETRIES = 3
    RETRY_DELAY = 1  # seconds

    def __init__(self, graph_id: str, graph_service):
        """
        Args:
            graph_id: The graph identifier for this simulation.
            graph_service: LocalGraphService instance (provides get_connection()).
        """
        self.graph_id = graph_id
        self.graph_service = graph_service

        self._activity_queue: Queue = Queue()

        self._platform_buffers: Dict[str, List[AgentActivity]] = {
            'twitter': [],
            'reddit': [],
        }
        self._buffer_lock = threading.Lock()

        self._running = False
        self._worker_thread: Optional[threading.Thread] = None

        # Stats
        self._total_activities = 0
        self._total_sent = 0
        self._total_items_sent = 0
        self._failed_count = 0
        self._skipped_count = 0

        logger.info(f"LocalGraphMemoryUpdater initialised: graph_id={graph_id}, batch_size={self.BATCH_SIZE}")

    def _get_platform_display_name(self, platform: str) -> str:
        return self.PLATFORM_DISPLAY_NAMES.get(platform.lower(), platform)

    def start(self):
        if self._running:
            return

        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name=f"LocalMemoryUpdater-{self.graph_id[:8]}",
        )
        self._worker_thread.start()
        logger.info(f"LocalGraphMemoryUpdater started: graph_id={self.graph_id}")

    def stop(self):
        self._running = False

        self._flush_remaining()

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=10)

        logger.info(
            f"LocalGraphMemoryUpdater stopped: graph_id={self.graph_id}, "
            f"total_activities={self._total_activities}, "
            f"batches_sent={self._total_sent}, "
            f"items_sent={self._total_items_sent}, "
            f"failed={self._failed_count}, "
            f"skipped={self._skipped_count}"
        )

    def add_activity(self, activity: AgentActivity):
        # Skip DO_NOTHING
        if activity.action_type == "DO_NOTHING":
            self._skipped_count += 1
            return

        self._activity_queue.put(activity)
        self._total_activities += 1
        logger.debug(f"Queued activity: {activity.agent_name} - {activity.action_type}")

    def add_activity_from_dict(self, data: Dict[str, Any], platform: str):
        # Skip event-type entries (not agent actions)
        if "event_type" in data:
            return

        activity = AgentActivity(
            platform=platform,
            agent_id=data.get("agent_id", 0),
            agent_name=data.get("agent_name", ""),
            action_type=data.get("action_type", ""),
            action_args=data.get("action_args", {}),
            round_num=data.get("round", 0),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
        )

        self.add_activity(activity)

    # ------------------------------------------------------------------
    # Worker loop
    # ------------------------------------------------------------------

    def _worker_loop(self):
        while self._running or not self._activity_queue.empty():
            try:
                try:
                    activity = self._activity_queue.get(timeout=1)

                    platform = activity.platform.lower()
                    with self._buffer_lock:
                        if platform not in self._platform_buffers:
                            self._platform_buffers[platform] = []
                        self._platform_buffers[platform].append(activity)

                        if len(self._platform_buffers[platform]) >= self.BATCH_SIZE:
                            batch = self._platform_buffers[platform][:self.BATCH_SIZE]
                            self._platform_buffers[platform] = self._platform_buffers[platform][self.BATCH_SIZE:]
                            self._send_batch_activities(batch, platform)
                            time.sleep(self.SEND_INTERVAL)

                except Empty:
                    pass

            except Exception as e:
                logger.error(f"Worker loop error: {e}")
                time.sleep(1)

    # ------------------------------------------------------------------
    # Batch insert into Kuzu
    # ------------------------------------------------------------------

    def _send_batch_activities(self, activities: List[AgentActivity], platform: str):
        """Insert activities as RELATES_TO edges in Kuzu."""
        if not activities:
            return

        for attempt in range(self.MAX_RETRIES):
            try:
                conn = self.graph_service.get_connection()

                for activity in activities:
                    relation = _ACTION_RELATION_MAP.get(activity.action_type)
                    if not relation:
                        # SEARCH_POSTS, SEARCH_USER, etc. -- skip
                        continue

                    fact = activity.to_episode_text()
                    agent_uuid = f"sim_agent_{activity.agent_id}"
                    action_uuid = f"sim_action_{activity.agent_id}_{activity.round_num}_{activity.action_type}"

                    # Ensure agent entity node exists.
                    # Kuzu does not support MERGE; query first, then conditionally create.
                    result = conn.execute(
                        "MATCH (e:Entity) WHERE e.uuid = $uuid RETURN e.uuid",
                        {"uuid": agent_uuid},
                    )
                    if not result.has_next():
                        conn.execute(
                            "CREATE (e:Entity {uuid: $uuid, graph_id: $gid, "
                            "name: $name, label: $label, summary: $summary, attributes: $attrs})",
                            {
                                "uuid": agent_uuid,
                                "gid": self.graph_id,
                                "name": activity.agent_name,
                                "label": "agent",
                                "summary": "",
                                "attrs": "{}",
                            },
                        )

                    # Create a unique action entity node to serve as the edge target.
                    # This avoids potential issues with self-referencing edges.
                    result = conn.execute(
                        "MATCH (e:Entity) WHERE e.uuid = $uuid RETURN e.uuid",
                        {"uuid": action_uuid},
                    )
                    if not result.has_next():
                        conn.execute(
                            "CREATE (e:Entity {uuid: $uuid, graph_id: $gid, "
                            "name: $name, label: $label, summary: $summary, attributes: $attrs})",
                            {
                                "uuid": action_uuid,
                                "gid": self.graph_id,
                                "name": f"{activity.action_type} (round {activity.round_num})",
                                "label": "action",
                                "summary": fact,
                                "attrs": "{}",
                            },
                        )

                    # Create the relationship edge
                    conn.execute(
                        "MATCH (a:Entity {uuid: $src}), (b:Entity {uuid: $tgt}) "
                        "CREATE (a)-[:RELATES_TO {relation: $rel, fact: $fact, "
                        "graph_id: $gid, created_at: $ts}]->(b)",
                        {
                            "src": agent_uuid,
                            "tgt": action_uuid,
                            "rel": relation,
                            "fact": fact,
                            "gid": self.graph_id,
                            "ts": activity.timestamp,
                        },
                    )

                self._total_sent += 1
                self._total_items_sent += len(activities)
                display_name = self._get_platform_display_name(platform)
                logger.info(
                    f"Inserted {len(activities)} activities ({display_name}) "
                    f"into graph {self.graph_id}"
                )
                return

            except Exception as e:
                if attempt < self.MAX_RETRIES - 1:
                    logger.warning(
                        f"Kuzu insert failed (attempt {attempt + 1}/{self.MAX_RETRIES}): {e}"
                    )
                    time.sleep(self.RETRY_DELAY * (attempt + 1))
                else:
                    logger.error(
                        f"Kuzu insert failed after {self.MAX_RETRIES} retries: {e}"
                    )
                    self._failed_count += 1

    def _flush_remaining(self):
        """Drain the queue and send any remaining buffered activities."""
        while not self._activity_queue.empty():
            try:
                activity = self._activity_queue.get_nowait()
                platform = activity.platform.lower()
                with self._buffer_lock:
                    if platform not in self._platform_buffers:
                        self._platform_buffers[platform] = []
                    self._platform_buffers[platform].append(activity)
            except Empty:
                break

        with self._buffer_lock:
            for platform, buffer in self._platform_buffers.items():
                if buffer:
                    display_name = self._get_platform_display_name(platform)
                    logger.info(f"Flushing {len(buffer)} remaining activities ({display_name})")
                    self._send_batch_activities(buffer, platform)
            for platform in self._platform_buffers:
                self._platform_buffers[platform] = []

    def get_stats(self) -> Dict[str, Any]:
        with self._buffer_lock:
            buffer_sizes = {p: len(b) for p, b in self._platform_buffers.items()}

        return {
            "graph_id": self.graph_id,
            "batch_size": self.BATCH_SIZE,
            "total_activities": self._total_activities,
            "batches_sent": self._total_sent,
            "items_sent": self._total_items_sent,
            "failed_count": self._failed_count,
            "skipped_count": self._skipped_count,
            "queue_size": self._activity_queue.qsize(),
            "buffer_sizes": buffer_sizes,
            "running": self._running,
        }


class LocalGraphMemoryManager:
    """
    Singleton manager for LocalGraphMemoryUpdater instances.
    Same pattern as ZepGraphMemoryManager.
    """

    _updaters: Dict[str, LocalGraphMemoryUpdater] = {}
    _lock = threading.Lock()

    @classmethod
    def create_updater(
        cls, simulation_id: str, graph_id: str, graph_service=None
    ) -> LocalGraphMemoryUpdater:
        """
        Create (or replace) a graph memory updater for a simulation.

        Args:
            simulation_id: Simulation identifier.
            graph_id: Kuzu graph identifier.
            graph_service: Optional LocalGraphService. If None, the app-wide
                singleton from config.get_graph_service() is used.

        Returns:
            A running LocalGraphMemoryUpdater.
        """
        if graph_service is None:
            from ..config import get_graph_service
            graph_service = get_graph_service()

        with cls._lock:
            if simulation_id in cls._updaters:
                cls._updaters[simulation_id].stop()

            updater = LocalGraphMemoryUpdater(graph_id, graph_service)
            updater.start()
            cls._updaters[simulation_id] = updater

            logger.info(
                f"Graph memory updater created: simulation_id={simulation_id}, graph_id={graph_id}"
            )
            return updater

    @classmethod
    def get_updater(cls, simulation_id: str) -> Optional[LocalGraphMemoryUpdater]:
        return cls._updaters.get(simulation_id)

    @classmethod
    def stop_updater(cls, simulation_id: str):
        with cls._lock:
            if simulation_id in cls._updaters:
                cls._updaters[simulation_id].stop()
                del cls._updaters[simulation_id]
                logger.info(f"Graph memory updater stopped: simulation_id={simulation_id}")

    _stop_all_done = False

    @classmethod
    def stop_all(cls):
        if cls._stop_all_done:
            return
        cls._stop_all_done = True

        with cls._lock:
            if cls._updaters:
                for simulation_id, updater in list(cls._updaters.items()):
                    try:
                        updater.stop()
                    except Exception as e:
                        logger.error(f"Failed to stop updater: simulation_id={simulation_id}, error={e}")
                cls._updaters.clear()
            logger.info("All graph memory updaters stopped")

    @classmethod
    def get_all_stats(cls) -> Dict[str, Dict[str, Any]]:
        return {
            sim_id: updater.get_stats()
            for sim_id, updater in cls._updaters.items()
        }
