"""
LocalGraphService 단위 테스트.
Kuzu DB 기반 엔터티 읽기/쿼리 동작을 검증한다.
"""

import json
import pytest
from unittest.mock import patch, MagicMock, PropertyMock

import sys
import importlib

# Import directly from the module file to avoid app.services.__init__.py
# which pulls in zep_cloud (not installed in test env).
_spec = importlib.util.spec_from_file_location(
    "local_graph_service",
    str(__import__("pathlib").Path(__file__).resolve().parent.parent / "app" / "services" / "local_graph_service.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

LocalGraphService = _mod.LocalGraphService
GraphInfo = _mod.GraphInfo
EntityNode = _mod.EntityNode
FilteredEntities = _mod.FilteredEntities


# ------------------------------------------------------------------
# 헬퍼: 테스트 데이터를 tmp_kuzu_db fixture에 직접 삽입
# ------------------------------------------------------------------

def _insert_test_data(conn, graph_id="test-graph"):
    """학생 2명, 교사 1명, Entity-only 1명 + 관계 2개를 삽입한다."""
    # 노드 삽입
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
    # Entity-only 노드 (label 없음 -> 필터링에서 제외)
    conn.execute(
        "CREATE (n:Entity {uuid: $uuid, graph_id: $gid, name: $name, "
        "label: $label, summary: $summary, attributes: $attrs})",
        {
            "uuid": "node-4",
            "gid": graph_id,
            "name": "Unknown",
            "label": "",
            "summary": "",
            "attrs": "",
        },
    )
    # 엣지 삽입
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
    """tmp_dir에 대해 LocalGraphService를 생성한다(LLM 미사용)."""
    return LocalGraphService(
        db_dir=tmp_dir,
        llm_base_url="http://localhost:8080/v1",
        llm_api_key="test-key",
        llm_model="openai/test-model",
    )


# ------------------------------------------------------------------
# 테스트
# ------------------------------------------------------------------


class TestLocalGraphServiceInit:
    """서비스 초기화 테스트."""

    def test_init_creates_schema(self, tmp_kuzu_db):
        """서비스 초기화 시 Entity/RELATES_TO 스키마가 이미 존재하면 에러 없이 통과한다."""
        tmp_dir, db, conn = tmp_kuzu_db
        # fixture가 이미 스키마를 생성했으므로 IF NOT EXISTS로 충돌 없이 생성
        svc = _make_service(tmp_dir)
        assert svc.db is not None


class TestGetAllNodesEdges:
    """노드/엣지 조회 테스트."""

    def test_get_all_nodes_empty(self, tmp_kuzu_db):
        """빈 그래프에서 노드 조회 시 빈 리스트를 반환한다."""
        tmp_dir, db, conn = tmp_kuzu_db
        svc = _make_service(tmp_dir)
        nodes = svc.get_all_nodes("nonexistent-graph")
        assert nodes == []

    def test_get_all_edges_empty(self, tmp_kuzu_db):
        """빈 그래프에서 엣지 조회 시 빈 리스트를 반환한다."""
        tmp_dir, db, conn = tmp_kuzu_db
        svc = _make_service(tmp_dir)
        edges = svc.get_all_edges("nonexistent-graph")
        assert edges == []

    def test_insert_and_query_nodes(self, tmp_kuzu_db):
        """노드를 삽입한 뒤 get_all_nodes로 올바르게 조회한다."""
        tmp_dir, db, conn = tmp_kuzu_db
        _insert_test_data(conn, "g1")
        svc = _make_service(tmp_dir)

        nodes = svc.get_all_nodes("g1")
        assert len(nodes) == 4

        names = {n["name"] for n in nodes}
        assert "Alice" in names
        assert "Bob" in names
        assert "Prof. Kim" in names

        # labels 확인
        alice = next(n for n in nodes if n["name"] == "Alice")
        assert "Student" in alice["labels"]
        assert "Entity" in alice["labels"]

        # attributes JSON 역직렬화 확인
        assert alice["attributes"]["age"] == 20

    def test_insert_and_query_edges(self, tmp_kuzu_db):
        """엣지를 삽입한 뒤 get_all_edges로 올바르게 조회한다."""
        tmp_dir, db, conn = tmp_kuzu_db
        _insert_test_data(conn, "g1")
        svc = _make_service(tmp_dir)

        edges = svc.get_all_edges("g1")
        assert len(edges) == 2

        facts = [e["fact"] for e in edges]
        assert any("Alice" in f for f in facts)
        assert any("Bob" in f for f in facts)


class TestFilterDefinedEntities:
    """엔터티 필터링 테스트."""

    def test_filter_all_types(self, tmp_kuzu_db):
        """타입 지정 없이 필터링하면 label이 있는 노드만 반환한다."""
        tmp_dir, db, conn = tmp_kuzu_db
        _insert_test_data(conn, "g1")
        svc = _make_service(tmp_dir)

        result = svc.filter_defined_entities("g1")
        assert isinstance(result, FilteredEntities)
        assert result.total_count == 4  # 전체 노드
        assert result.filtered_count == 3  # Entity-only 제외
        assert "Student" in result.entity_types
        assert "Teacher" in result.entity_types

    def test_filter_by_type(self, tmp_kuzu_db):
        """특정 타입으로 필터링한다."""
        tmp_dir, db, conn = tmp_kuzu_db
        _insert_test_data(conn, "g1")
        svc = _make_service(tmp_dir)

        result = svc.filter_defined_entities("g1", defined_entity_types=["Student"])
        assert result.filtered_count == 2
        assert all(e.get_entity_type() == "Student" for e in result.entities)

    def test_filter_enriches_edges(self, tmp_kuzu_db):
        """enrich_with_edges=True 시 연관 엣지/노드가 채워진다."""
        tmp_dir, db, conn = tmp_kuzu_db
        _insert_test_data(conn, "g1")
        svc = _make_service(tmp_dir)

        result = svc.filter_defined_entities("g1", defined_entity_types=["Student"])
        alice = next(e for e in result.entities if e.name == "Alice")
        assert len(alice.related_edges) == 1
        assert alice.related_edges[0]["direction"] == "outgoing"
        assert alice.related_edges[0]["edge_name"] == "ENROLLED_IN"
        assert len(alice.related_nodes) == 1
        assert alice.related_nodes[0]["name"] == "Prof. Kim"

    def test_filter_without_edges(self, tmp_kuzu_db):
        """enrich_with_edges=False 시 연관 정보가 비어 있다."""
        tmp_dir, db, conn = tmp_kuzu_db
        _insert_test_data(conn, "g1")
        svc = _make_service(tmp_dir)

        result = svc.filter_defined_entities(
            "g1", defined_entity_types=["Student"], enrich_with_edges=False
        )
        for entity in result.entities:
            assert entity.related_edges == []
            assert entity.related_nodes == []


class TestGraphInfo:
    """GraphInfo 조회 테스트."""

    def test_get_graph_info(self, tmp_kuzu_db):
        """노드/엣지 수와 엔터티 타입을 올바르게 집계한다."""
        tmp_dir, db, conn = tmp_kuzu_db
        _insert_test_data(conn, "g1")
        svc = _make_service(tmp_dir)

        info = svc.get_graph_info("g1")
        assert isinstance(info, GraphInfo)
        assert info.graph_id == "g1"
        assert info.node_count == 4
        assert info.edge_count == 2
        assert set(info.entity_types) == {"Student", "Teacher"}

    def test_graph_info_to_dict(self, tmp_kuzu_db):
        """to_dict() 직렬화를 검증한다."""
        tmp_dir, db, conn = tmp_kuzu_db
        _insert_test_data(conn, "g1")
        svc = _make_service(tmp_dir)

        d = svc.get_graph_info("g1").to_dict()
        assert d["graph_id"] == "g1"
        assert d["node_count"] == 4
        assert isinstance(d["entity_types"], list)


class TestGraphData:
    """Zep 호환 그래프 데이터 포맷 테스트."""

    def test_get_graph_data_format(self, tmp_kuzu_db):
        """반환 dict에 Zep 호환 temporal 필드(None)가 포함된다."""
        tmp_dir, db, conn = tmp_kuzu_db
        _insert_test_data(conn, "g1")
        svc = _make_service(tmp_dir)

        data = svc.get_graph_data("g1")
        assert data["graph_id"] == "g1"
        assert data["node_count"] == 4
        assert data["edge_count"] == 2

        # 노드 필드
        node = data["nodes"][0]
        assert "uuid" in node
        assert "name" in node
        assert "labels" in node
        assert "created_at" in node  # None

        # 엣지 temporal 필드
        edge = data["edges"][0]
        assert "valid_at" in edge
        assert edge["valid_at"] is None
        assert "invalid_at" in edge
        assert "expired_at" in edge
        assert "episodes" in edge
        assert isinstance(edge["episodes"], list)

        # source/target 이름 매핑
        assert edge["source_node_name"] != ""
        assert edge["target_node_name"] != ""


class TestDeleteGraph:
    """그래프 삭제 테스트."""

    def test_delete_graph(self, tmp_kuzu_db):
        """삭제 후 노드/엣지가 비어야 한다."""
        tmp_dir, db, conn = tmp_kuzu_db
        _insert_test_data(conn, "g1")
        svc = _make_service(tmp_dir)

        # 삭제 전 확인
        assert len(svc.get_all_nodes("g1")) == 4
        assert len(svc.get_all_edges("g1")) == 2

        svc.delete_graph("g1")

        assert svc.get_all_nodes("g1") == []
        assert svc.get_all_edges("g1") == []

    def test_delete_graph_isolation(self, tmp_kuzu_db):
        """다른 graph_id의 데이터는 삭제되지 않는다."""
        tmp_dir, db, conn = tmp_kuzu_db
        _insert_test_data(conn, "g1")
        # g2에는 별도 노드 1개
        conn.execute(
            "CREATE (n:Entity {uuid: 'node-g2-1', graph_id: 'g2', name: 'Carol', "
            "label: 'Student', summary: '', attributes: ''})"
        )
        svc = _make_service(tmp_dir)

        svc.delete_graph("g1")

        assert svc.get_all_nodes("g1") == []
        assert len(svc.get_all_nodes("g2")) == 1


class TestEntityWithContext:
    """단일 엔터티 + 컨텍스트 조회 테스트."""

    def test_get_entity_with_context(self, tmp_kuzu_db):
        """엔터티와 연관 엣지/노드를 조회한다."""
        tmp_dir, db, conn = tmp_kuzu_db
        _insert_test_data(conn, "g1")
        svc = _make_service(tmp_dir)

        entity = svc.get_entity_with_context("g1", "node-1")
        assert entity is not None
        assert entity.name == "Alice"
        assert entity.get_entity_type() == "Student"
        assert len(entity.related_edges) == 1
        assert entity.related_edges[0]["edge_name"] == "ENROLLED_IN"

    def test_get_entity_not_found(self, tmp_kuzu_db):
        """존재하지 않는 UUID는 None을 반환한다."""
        tmp_dir, db, conn = tmp_kuzu_db
        svc = _make_service(tmp_dir)
        assert svc.get_entity_with_context("g1", "no-such-uuid") is None


class TestGetEntitiesByType:
    """타입별 엔터티 조회 테스트."""

    def test_get_entities_by_type(self, tmp_kuzu_db):
        """Student 타입으로 조회하면 2명이 반환된다."""
        tmp_dir, db, conn = tmp_kuzu_db
        _insert_test_data(conn, "g1")
        svc = _make_service(tmp_dir)

        students = svc.get_entities_by_type("g1", "Student")
        assert len(students) == 2
        assert all(isinstance(s, EntityNode) for s in students)


class TestSearchEntityContext:
    """search_entity_context 테스트."""

    def test_search_entity_context(self, tmp_kuzu_db):
        """엔터티 이름으로 검색 시 관련 사실이 반환된다."""
        tmp_dir, db, conn = tmp_kuzu_db
        _insert_test_data(conn, "g1")
        svc = _make_service(tmp_dir)

        ctx = svc.search_entity_context("g1", "Alice")
        assert len(ctx["facts"]) >= 1
        assert any("Alice" in f for f in ctx["facts"])
        assert ctx["context"] != ""

    def test_search_entity_context_target(self, tmp_kuzu_db):
        """엣지 대상 엔터티(Prof. Kim)를 검색하면 incoming 사실이 반환된다."""
        tmp_dir, db, conn = tmp_kuzu_db
        _insert_test_data(conn, "g1")
        svc = _make_service(tmp_dir)

        ctx = svc.search_entity_context("g1", "Prof. Kim")
        assert len(ctx["facts"]) == 2  # Alice, Bob 모두 incoming

    def test_search_entity_context_empty(self, tmp_kuzu_db):
        """존재하지 않는 엔터티를 검색하면 빈 결과를 반환한다."""
        tmp_dir, db, conn = tmp_kuzu_db
        svc = _make_service(tmp_dir)

        ctx = svc.search_entity_context("g1", "Nobody")
        assert ctx["facts"] == []
        assert ctx["context"] == ""


class TestDataclassContracts:
    """Dataclass 계약(to_dict, get_entity_type) 테스트."""

    def test_entity_node_to_dict(self, tmp_kuzu_db):
        """EntityNode.to_dict()가 모든 필드를 포함한다."""
        tmp_dir, db, conn = tmp_kuzu_db
        _insert_test_data(conn, "g1")
        svc = _make_service(tmp_dir)

        entity = svc.get_entity_with_context("g1", "node-1")
        d = entity.to_dict()
        assert set(d.keys()) == {
            "uuid", "name", "labels", "summary",
            "attributes", "related_edges", "related_nodes",
        }

    def test_filtered_entities_to_dict(self, tmp_kuzu_db):
        """FilteredEntities.to_dict()가 올바르게 직렬화된다."""
        tmp_dir, db, conn = tmp_kuzu_db
        _insert_test_data(conn, "g1")
        svc = _make_service(tmp_dir)

        result = svc.filter_defined_entities("g1")
        d = result.to_dict()
        assert "entities" in d
        assert "entity_types" in d
        assert isinstance(d["entity_types"], list)
        assert d["total_count"] == 4
        assert d["filtered_count"] == 3


# ------------------------------------------------------------------
# build_graph 테스트 (kg-gen 모킹)
# ------------------------------------------------------------------


def _make_mock_kg():
    """kg-gen KGGen 목 객체를 생성한다."""
    mock_graph = MagicMock()
    mock_graph.entities = {"Alice", "Bob"}
    mock_graph.relations = {("Alice", "studies_under", "Bob")}

    mock_kg = MagicMock()
    mock_kg.generate.return_value = mock_graph
    mock_kg.aggregate.return_value = mock_graph
    mock_kg.cluster.return_value = mock_graph
    return mock_kg, mock_graph


class TestLocalGraphServiceBuild:
    """build_graph 메서드 테스트."""

    def test_build_graph_from_text(self, tmp_kuzu_db):
        """build_graph가 엔터티와 엣지를 Kuzu에 생성한다."""
        tmp_dir, db, conn = tmp_kuzu_db
        svc = _make_service(tmp_dir)

        mock_kg, mock_graph = _make_mock_kg()

        with patch.object(type(svc), "kg", new_callable=PropertyMock, return_value=mock_kg):
            ontology = {
                "entity_types": [{"name": "student"}, {"name": "professor"}],
            }
            graph_id = svc.build_graph(
                text="Alice studies under Bob.",
                ontology=ontology,
            )

        assert graph_id.startswith("mirofish_")

        nodes = svc.get_all_nodes(graph_id)
        assert len(nodes) == 2

        names = {n["name"] for n in nodes}
        assert "Alice" in names
        assert "Bob" in names

        info = svc.get_graph_info(graph_id)
        assert info.edge_count == 1

    def test_build_graph_progress_callback(self, tmp_kuzu_db):
        """progress_callback이 빌드 중 호출된다."""
        tmp_dir, db, conn = tmp_kuzu_db
        svc = _make_service(tmp_dir)

        mock_kg, _ = _make_mock_kg()
        calls = []

        def callback(msg, ratio):
            calls.append((msg, ratio))

        with patch.object(type(svc), "kg", new_callable=PropertyMock, return_value=mock_kg):
            svc.build_graph(
                text="Alice studies under Bob.",
                ontology={"entity_types": []},
                progress_callback=callback,
            )

        assert len(calls) >= 4  # 분할, 청크 처리, 병합, 완료 등
        # 비율이 단조 증가하는지 확인
        ratios = [r for _, r in calls]
        assert ratios == sorted(ratios)

    def test_build_graph_empty_chunks(self, tmp_kuzu_db):
        """모든 청크가 실패하고 재시도도 빈 그래프이면 graph_id만 반환된다."""
        tmp_dir, db, conn = tmp_kuzu_db
        svc = _make_service(tmp_dir)

        mock_kg = MagicMock()
        # generate가 entities/relations 모두 빈 그래프를 반환
        empty_graph = MagicMock()
        empty_graph.entities = set()
        empty_graph.relations = set()
        mock_kg.generate.return_value = empty_graph

        with patch.object(type(svc), "kg", new_callable=PropertyMock, return_value=mock_kg):
            graph_id = svc.build_graph(
                text="Some text.",
                ontology={"entity_types": []},
            )

        assert graph_id.startswith("mirofish_")
        nodes = svc.get_all_nodes(graph_id)
        assert len(nodes) == 0

    def test_build_graph_chunk_failure_continues(self, tmp_kuzu_db):
        """청크 처리 중 예외가 발생해도 나머지 청크를 계속 처리한다."""
        tmp_dir, db, conn = tmp_kuzu_db
        svc = _make_service(tmp_dir)

        good_graph = MagicMock()
        good_graph.entities = {"Entity1"}
        good_graph.relations = set()

        mock_kg = MagicMock()
        # 첫 번째 호출은 예외, 두 번째는 성공
        mock_kg.generate.side_effect = [Exception("LLM error"), good_graph]
        mock_kg.aggregate.return_value = good_graph
        mock_kg.cluster.return_value = good_graph

        with patch.object(type(svc), "kg", new_callable=PropertyMock, return_value=mock_kg):
            # 텍스트를 충분히 길게 해서 2개 청크가 생기도록
            graph_id = svc.build_graph(
                text="A" * 100,
                ontology={"entity_types": []},
                chunk_size=60,
            )

        nodes = svc.get_all_nodes(graph_id)
        assert len(nodes) == 1
        assert nodes[0]["name"] == "Entity1"


class TestOntologyToContext:
    """_ontology_to_context 헬퍼 테스트."""

    def test_with_entity_and_edge_types(self, tmp_kuzu_db):
        """엔터티 타입과 엣지 타입이 모두 포함된 컨텍스트 문자열을 생성한다."""
        tmp_dir, db, conn = tmp_kuzu_db
        svc = _make_service(tmp_dir)

        ontology = {
            "entity_types": [{"name": "Person"}, {"name": "Organization"}],
            "edge_types": [{"name": "works_at"}, {"name": "manages"}],
        }
        ctx = svc._ontology_to_context(ontology)
        assert "Person" in ctx
        assert "Organization" in ctx
        assert "works_at" in ctx
        assert "manages" in ctx

    def test_with_empty_ontology(self, tmp_kuzu_db):
        """빈 온톨로지는 빈 문자열을 반환한다."""
        tmp_dir, db, conn = tmp_kuzu_db
        svc = _make_service(tmp_dir)

        ctx = svc._ontology_to_context({})
        assert ctx == ""

    def test_with_entity_types_only(self, tmp_kuzu_db):
        """엔터티 타입만 있으면 해당 부분만 포함된다."""
        tmp_dir, db, conn = tmp_kuzu_db
        svc = _make_service(tmp_dir)

        ontology = {"entity_types": [{"name": "Animal"}]}
        ctx = svc._ontology_to_context(ontology)
        assert "Animal" in ctx
        assert "relationship" not in ctx.lower()
