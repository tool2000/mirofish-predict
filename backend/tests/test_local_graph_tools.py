"""
LocalGraphToolsService 단위 테스트.
QuickSearch, PanoramaSearch, InsightForge, 통계 조회 등을 검증한다.
"""

import json
import pytest
from unittest.mock import MagicMock, patch

import importlib

# Import directly from the module file to avoid app.services.__init__.py
# which pulls in zep_cloud (not installed in test env).
_spec = importlib.util.spec_from_file_location(
    "local_graph_tools",
    str(
        __import__("pathlib").Path(__file__).resolve().parent.parent
        / "app"
        / "services"
        / "local_graph_tools.py"
    ),
)
_mod = importlib.util.module_from_spec(_spec)

# Stub out parent-package imports so the module loads in isolation.
import sys
import types

# Create stub modules for the relative imports used by local_graph_tools.
_app_pkg = types.ModuleType("app")
_utils_pkg = types.ModuleType("app.utils")
_config_mod = types.ModuleType("app.config")
_logger_mod = types.ModuleType("app.utils.logger")
_llm_mod = types.ModuleType("app.utils.llm_client")

# Provide a no-op get_logger
import logging
_logger_mod.get_logger = logging.getLogger

sys.modules.setdefault("app", _app_pkg)
sys.modules.setdefault("app.utils", _utils_pkg)
sys.modules.setdefault("app.utils.logger", _logger_mod)
sys.modules.setdefault("app.utils.llm_client", _llm_mod)
sys.modules.setdefault("app.config", _config_mod)

# Also stub the double-dot relative references used inside the module.
_parent_pkg = types.ModuleType("local_graph_tools.__parent__")
sys.modules.setdefault("local_graph_tools", _mod)

# Patch the module's package so relative imports resolve.
_mod.__package__ = "app.services"
_services_pkg = types.ModuleType("app.services")
sys.modules.setdefault("app.services", _services_pkg)

_spec.loader.exec_module(_mod)

LocalGraphToolsService = _mod.LocalGraphToolsService
SearchResult = _mod.SearchResult
NodeInfo = _mod.NodeInfo
EdgeInfo = _mod.EdgeInfo
InsightForgeResult = _mod.InsightForgeResult
PanoramaResult = _mod.PanoramaResult
InterviewResult = _mod.InterviewResult

# Also need LocalGraphService for creating the graph_service mock target.
_gs_spec = importlib.util.spec_from_file_location(
    "local_graph_service",
    str(
        __import__("pathlib").Path(__file__).resolve().parent.parent
        / "app"
        / "services"
        / "local_graph_service.py"
    ),
)
_gs_mod = importlib.util.module_from_spec(_gs_spec)
_gs_spec.loader.exec_module(_gs_mod)
LocalGraphService = _gs_mod.LocalGraphService
GraphInfo = _gs_mod.GraphInfo


# ------------------------------------------------------------------
# 헬퍼: 테스트 데이터를 tmp_kuzu_db fixture에 직접 삽입
# ------------------------------------------------------------------


def _insert_test_data(conn, graph_id="test-graph"):
    """학생 2명, 교사 1명 + 관계 2개를 삽입한다."""
    conn.execute(
        "CREATE (n:Entity {uuid: $uuid, graph_id: $gid, name: $name, "
        "label: $label, summary: $summary, attributes: $attrs})",
        {
            "uuid": "node-1",
            "gid": graph_id,
            "name": "Alice",
            "label": "Student",
            "summary": "Alice is a student",
            "attrs": json.dumps({"age": 20}),
        },
    )
    conn.execute(
        "CREATE (n:Entity {uuid: $uuid, graph_id: $gid, name: $name, "
        "label: $label, summary: $summary, attributes: $attrs})",
        {
            "uuid": "node-2",
            "gid": graph_id,
            "name": "Bob",
            "label": "Student",
            "summary": "Bob is a student",
            "attrs": json.dumps({"age": 21}),
        },
    )
    conn.execute(
        "CREATE (n:Entity {uuid: $uuid, graph_id: $gid, name: $name, "
        "label: $label, summary: $summary, attributes: $attrs})",
        {
            "uuid": "node-3",
            "gid": graph_id,
            "name": "Prof. Kim",
            "label": "Teacher",
            "summary": "Prof. Kim teaches math",
            "attrs": json.dumps({}),
        },
    )
    conn.execute(
        "MATCH (a:Entity), (b:Entity) WHERE a.uuid = 'node-1' AND b.uuid = 'node-3' "
        "CREATE (a)-[:RELATES_TO {relation: 'ENROLLED_IN', fact: 'Alice is enrolled in Prof. Kim class', "
        "graph_id: $gid, created_at: '2025-01-01'}]->(b)",
        {"gid": graph_id},
    )
    conn.execute(
        "MATCH (a:Entity), (b:Entity) WHERE a.uuid = 'node-2' AND b.uuid = 'node-3' "
        "CREATE (a)-[:RELATES_TO {relation: 'ENROLLED_IN', fact: 'Bob is enrolled in Prof. Kim class', "
        "graph_id: $gid, created_at: '2025-01-02'}]->(b)",
        {"gid": graph_id},
    )


def _make_service(tmp_dir):
    """tmp_dir에 대해 LocalGraphToolsService를 생성한다 (LLM 모킹)."""
    graph_service = LocalGraphService(
        db_dir=tmp_dir,
        llm_base_url="http://localhost:8080/v1",
        llm_api_key="test-key",
        llm_model="openai/test-model",
    )
    llm_client = MagicMock()
    return LocalGraphToolsService(
        graph_service=graph_service,
        llm_client=llm_client,
    )


# ------------------------------------------------------------------
# 테스트
# ------------------------------------------------------------------


class TestQuickSearch:
    """QuickSearch 테스트."""

    def test_finds_matching_facts(self, tmp_kuzu_db):
        """키워드가 포함된 사실을 검색한다."""
        tmp_dir, db, conn = tmp_kuzu_db
        _insert_test_data(conn, "g1")
        svc = _make_service(tmp_dir)

        result = svc.quick_search("g1", "Alice")
        assert isinstance(result, SearchResult)
        assert len(result.facts) >= 1
        assert any("Alice" in f for f in result.facts)
        assert result.total_count > 0

    def test_finds_matching_nodes(self, tmp_kuzu_db):
        """엔터티 이름으로 노드를 검색한다."""
        tmp_dir, db, conn = tmp_kuzu_db
        _insert_test_data(conn, "g1")
        svc = _make_service(tmp_dir)

        result = svc.quick_search("g1", "Bob")
        assert len(result.nodes) >= 1
        assert any(n["name"] == "Bob" for n in result.nodes)

    def test_empty_result_for_no_match(self, tmp_kuzu_db):
        """매칭되지 않는 키워드는 빈 결과를 반환한다."""
        tmp_dir, db, conn = tmp_kuzu_db
        _insert_test_data(conn, "g1")
        svc = _make_service(tmp_dir)

        result = svc.quick_search("g1", "NONEXISTENT_KEYWORD_XYZ")
        assert result.total_count == 0
        assert result.facts == []

    def test_search_result_to_dict(self, tmp_kuzu_db):
        """SearchResult.to_dict()가 올바르게 직렬화된다."""
        tmp_dir, db, conn = tmp_kuzu_db
        _insert_test_data(conn, "g1")
        svc = _make_service(tmp_dir)

        result = svc.quick_search("g1", "Alice")
        d = result.to_dict()
        assert "facts" in d
        assert "query" in d
        assert d["query"] == "Alice"

    def test_search_result_to_text(self, tmp_kuzu_db):
        """SearchResult.to_text()가 텍스트를 반환한다."""
        tmp_dir, db, conn = tmp_kuzu_db
        _insert_test_data(conn, "g1")
        svc = _make_service(tmp_dir)

        result = svc.quick_search("g1", "Alice")
        text = result.to_text()
        assert "Alice" in text


class TestGetGraphStatistics:
    """그래프 통계 테스트."""

    def test_returns_counts(self, tmp_kuzu_db):
        """노드/엣지 수를 올바르게 반환한다."""
        tmp_dir, db, conn = tmp_kuzu_db
        _insert_test_data(conn, "g1")
        svc = _make_service(tmp_dir)

        stats = svc.get_graph_statistics("g1")
        assert stats["total_nodes"] == 3
        assert stats["total_edges"] == 2
        assert stats["graph_id"] == "g1"

    def test_empty_graph(self, tmp_kuzu_db):
        """빈 그래프의 통계는 0이다."""
        tmp_dir, db, conn = tmp_kuzu_db
        svc = _make_service(tmp_dir)

        stats = svc.get_graph_statistics("nonexistent")
        assert stats["total_nodes"] == 0
        assert stats["total_edges"] == 0


class TestPanoramaSearch:
    """PanoramaSearch 테스트."""

    def test_returns_all_nodes_and_edges(self, tmp_kuzu_db):
        """전체 노드와 엣지를 반환한다."""
        tmp_dir, db, conn = tmp_kuzu_db
        _insert_test_data(conn, "g1")
        svc = _make_service(tmp_dir)

        result = svc.panorama_search("g1", "student")
        assert isinstance(result, PanoramaResult)
        assert result.total_nodes == 3
        assert result.total_edges == 2
        assert len(result.all_nodes) == 3
        assert len(result.all_edges) == 2

    def test_active_facts_populated(self, tmp_kuzu_db):
        """모든 사실이 active로 분류된다 (로컬 스택)."""
        tmp_dir, db, conn = tmp_kuzu_db
        _insert_test_data(conn, "g1")
        svc = _make_service(tmp_dir)

        result = svc.panorama_search("g1", "enrolled")
        assert result.active_count == 2
        assert result.historical_count == 0
        assert result.historical_facts == []

    def test_panorama_to_dict(self, tmp_kuzu_db):
        """PanoramaResult.to_dict()가 올바르게 직렬화된다."""
        tmp_dir, db, conn = tmp_kuzu_db
        _insert_test_data(conn, "g1")
        svc = _make_service(tmp_dir)

        result = svc.panorama_search("g1", "student")
        d = result.to_dict()
        assert "all_nodes" in d
        assert "all_edges" in d
        assert "active_facts" in d
        assert d["total_nodes"] == 3

    def test_panorama_to_text(self, tmp_kuzu_db):
        """PanoramaResult.to_text()가 텍스트를 반환한다."""
        tmp_dir, db, conn = tmp_kuzu_db
        _insert_test_data(conn, "g1")
        svc = _make_service(tmp_dir)

        result = svc.panorama_search("g1", "student")
        text = result.to_text()
        assert "노드" in text


class TestInsightForge:
    """InsightForge 테스트."""

    def test_returns_facts_from_subqueries(self, tmp_kuzu_db):
        """하위 질문을 통해 사실을 수집한다."""
        tmp_dir, db, conn = tmp_kuzu_db
        _insert_test_data(conn, "g1")
        svc = _make_service(tmp_dir)

        # LLM chat_json 모킹: 하위 질문 반환
        svc._llm_client.chat_json.return_value = {
            "sub_queries": ["Alice", "Bob", "enrolled"]
        }

        result = svc.insight_forge("g1", "students", "학생 분석")
        assert isinstance(result, InsightForgeResult)
        assert result.total_facts >= 1
        assert len(result.sub_queries) == 3

    def test_fallback_on_llm_failure(self, tmp_kuzu_db):
        """LLM 실패 시 폴백 질문을 사용한다."""
        tmp_dir, db, conn = tmp_kuzu_db
        _insert_test_data(conn, "g1")
        svc = _make_service(tmp_dir)

        # LLM 실패 시뮬레이션
        svc._llm_client.chat_json.side_effect = Exception("LLM Error")

        result = svc.insight_forge("g1", "Alice", "학생 분석")
        assert isinstance(result, InsightForgeResult)
        # 폴백 질문이 사용됨
        assert len(result.sub_queries) >= 1

    def test_insight_forge_to_dict(self, tmp_kuzu_db):
        """InsightForgeResult.to_dict()가 올바르게 직렬화된다."""
        tmp_dir, db, conn = tmp_kuzu_db
        _insert_test_data(conn, "g1")
        svc = _make_service(tmp_dir)

        svc._llm_client.chat_json.return_value = {
            "sub_queries": ["Alice"]
        }

        result = svc.insight_forge("g1", "students", "분석")
        d = result.to_dict()
        assert "semantic_facts" in d
        assert "entity_insights" in d
        assert "sub_queries" in d


class TestEdgeInfoProperties:
    """EdgeInfo 속성 테스트."""

    def test_is_expired_always_false(self):
        """로컬 스택에서 is_expired는 항상 False이다."""
        edge = EdgeInfo(
            uuid="e1",
            name="REL",
            fact="test fact",
            source_node_uuid="n1",
            target_node_uuid="n2",
        )
        assert edge.is_expired is False

    def test_is_invalid_always_false(self):
        """로컬 스택에서 is_invalid는 항상 False이다."""
        edge = EdgeInfo(
            uuid="e1",
            name="REL",
            fact="test fact",
            source_node_uuid="n1",
            target_node_uuid="n2",
            invalid_at="2025-01-01",  # 값이 있어도 False
        )
        assert edge.is_invalid is False

    def test_edge_to_text(self):
        """EdgeInfo.to_text()가 텍스트를 반환한다."""
        edge = EdgeInfo(
            uuid="e1",
            name="ENROLLED_IN",
            fact="Alice is enrolled",
            source_node_uuid="n1",
            target_node_uuid="n2",
            source_node_name="Alice",
            target_node_name="Prof. Kim",
        )
        text = edge.to_text()
        assert "Alice" in text
        assert "ENROLLED_IN" in text


class TestNodeInfo:
    """NodeInfo 테스트."""

    def test_to_dict(self):
        """NodeInfo.to_dict()가 모든 필드를 포함한다."""
        node = NodeInfo(
            uuid="n1",
            name="Alice",
            labels=["Student", "Entity"],
            summary="A student",
            attributes={"age": 20},
        )
        d = node.to_dict()
        assert d["uuid"] == "n1"
        assert d["name"] == "Alice"
        assert "Student" in d["labels"]
        assert d["attributes"]["age"] == 20

    def test_to_text(self):
        """NodeInfo.to_text()가 엔터티 타입을 표시한다."""
        node = NodeInfo(
            uuid="n1",
            name="Alice",
            labels=["Student", "Entity"],
            summary="A student",
            attributes={},
        )
        text = node.to_text()
        assert "Alice" in text
        assert "Student" in text


class TestGetEntitySummary:
    """엔터티 요약 테스트."""

    def test_entity_summary(self, tmp_kuzu_db):
        """엔터티 이름으로 요약 정보를 반환한다."""
        tmp_dir, db, conn = tmp_kuzu_db
        _insert_test_data(conn, "g1")
        svc = _make_service(tmp_dir)

        result = svc.get_entity_summary("g1", "Alice")
        assert result["entity_name"] == "Alice"
        assert result["entity_info"] is not None
        assert result["entity_info"]["name"] == "Alice"

    def test_entity_summary_not_found(self, tmp_kuzu_db):
        """존재하지 않는 엔터티는 entity_info가 None이다."""
        tmp_dir, db, conn = tmp_kuzu_db
        svc = _make_service(tmp_dir)

        result = svc.get_entity_summary("g1", "Nobody")
        assert result["entity_info"] is None


class TestGetSimulationContext:
    """시뮬레이션 컨텍스트 테스트."""

    def test_returns_context(self, tmp_kuzu_db):
        """시뮬레이션 컨텍스트를 반환한다."""
        tmp_dir, db, conn = tmp_kuzu_db
        _insert_test_data(conn, "g1")
        svc = _make_service(tmp_dir)

        ctx = svc.get_simulation_context("g1", "학생 시뮬레이션")
        assert "simulation_requirement" in ctx
        assert "graph_statistics" in ctx
        assert ctx["total_entities"] > 0
