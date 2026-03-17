"""
로컬 그래프 서비스.
kg-gen + Kuzu DB를 사용해 GraphBuilderService + ZepEntityReader를 대체한다.
"""

import uuid
import json
import threading
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, field

import kuzu


@dataclass
class GraphInfo:
    """그래프 정보."""
    graph_id: str
    node_count: int
    edge_count: int
    entity_types: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "entity_types": self.entity_types,
        }


@dataclass
class EntityNode:
    """엔터티 노드 데이터 구조."""
    uuid: str
    name: str
    labels: List[str]
    summary: str
    attributes: Dict[str, Any]
    # 연관 엣지 정보
    related_edges: List[Dict[str, Any]] = field(default_factory=list)
    # 연관된 다른 노드 정보
    related_nodes: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "labels": self.labels,
            "summary": self.summary,
            "attributes": self.attributes,
            "related_edges": self.related_edges,
            "related_nodes": self.related_nodes,
        }

    def get_entity_type(self) -> Optional[str]:
        """엔터티 타입을 반환한다(`Entity` 기본 라벨 제외)."""
        for label in self.labels:
            if label not in ["Entity", "Node"]:
                return label
        return None


@dataclass
class FilteredEntities:
    """필터링된 엔터티 집합."""
    entities: List[EntityNode]
    entity_types: Set[str]
    total_count: int
    filtered_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entities": [e.to_dict() for e in self.entities],
            "entity_types": list(self.entity_types),
            "total_count": self.total_count,
            "filtered_count": self.filtered_count,
        }


class LocalGraphService:
    """kg-gen + Kuzu 통합 서비스. GraphBuilderService + ZepEntityReader를 대체한다."""

    def __init__(self, db_dir: str, llm_base_url: str, llm_api_key: str, llm_model: str):
        import os
        # Kuzu 0.11+ creates a single file at db_dir; ensure the parent exists.
        os.makedirs(os.path.dirname(os.path.abspath(db_dir)), exist_ok=True)
        self.db = kuzu.Database(db_dir)
        self._local = threading.local()
        self._init_schema()
        # kg-gen 초기화 파라미터 저장 (실제 인스턴스는 최초 사용 시 lazy 생성)
        self._llm_model = llm_model
        self._llm_api_key = llm_api_key
        self._llm_base_url = llm_base_url
        self._kg: Any = None

    @property
    def kg(self):
        """KGGen 인스턴스를 lazy 생성한다 (빌드 시점에만 사용)."""
        if self._kg is None:
            from kg_gen import KGGen
            self._kg = KGGen(
                model=self._llm_model,
                api_key=self._llm_api_key,
                base_url=self._llm_base_url,
            )
        return self._kg

    def get_connection(self) -> kuzu.Connection:
        """스레드별 Kuzu 연결을 반환한다."""
        if not hasattr(self._local, 'conn'):
            self._local.conn = kuzu.Connection(self.db)
        return self._local.conn

    def _init_schema(self):
        """Entity 노드 테이블과 RELATES_TO 관계 테이블을 생성한다."""
        conn = kuzu.Connection(self.db)
        conn.execute(
            "CREATE NODE TABLE IF NOT EXISTS Entity ("
            "uuid STRING PRIMARY KEY, "
            "graph_id STRING, "
            "name STRING, "
            "label STRING, "
            "summary STRING, "
            "attributes STRING"
            ")"
        )
        conn.execute(
            "CREATE REL TABLE IF NOT EXISTS RELATES_TO ("
            "FROM Entity TO Entity, "
            "relation STRING, "
            "fact STRING, "
            "graph_id STRING, "
            "created_at STRING"
            ")"
        )

    # ------------------------------------------------------------------
    # 노드/엣지 조회
    # ------------------------------------------------------------------

    def get_all_nodes(self, graph_id: str) -> List[Dict[str, Any]]:
        """그래프의 전체 노드를 조회한다."""
        conn = self.get_connection()
        result = conn.execute(
            "MATCH (n:Entity) WHERE n.graph_id = $gid "
            "RETURN n.uuid, n.name, n.label, n.summary, n.attributes",
            {"gid": graph_id},
        )
        nodes = []
        while result.has_next():
            row = result.get_next()
            nodes.append({
                "uuid": row[0],
                "name": row[1],
                "labels": [row[2], "Entity"] if row[2] else ["Entity"],
                "summary": row[3] or "",
                "attributes": json.loads(row[4]) if row[4] else {},
            })
        return nodes

    def get_all_edges(self, graph_id: str) -> List[Dict[str, Any]]:
        """그래프의 전체 엣지를 조회한다."""
        conn = self.get_connection()
        result = conn.execute(
            "MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity) "
            "WHERE r.graph_id = $gid "
            "RETURN r.relation, r.fact, a.uuid, b.uuid, r.created_at",
            {"gid": graph_id},
        )
        edges = []
        while result.has_next():
            row = result.get_next()
            edges.append({
                "name": row[0] or "",
                "fact": row[1] or "",
                "source_node_uuid": row[2],
                "target_node_uuid": row[3],
                "created_at": row[4],
                "attributes": {},
            })
        return edges

    # ------------------------------------------------------------------
    # 그래프 메타 정보
    # ------------------------------------------------------------------

    def get_graph_info(self, graph_id: str) -> GraphInfo:
        """그래프 노드/엣지 개수 및 엔터티 타입을 반환한다."""
        nodes = self.get_all_nodes(graph_id)
        edges = self.get_all_edges(graph_id)
        entity_types: Set[str] = set()
        for node in nodes:
            for label in node.get("labels", []):
                if label not in ["Entity", "Node"]:
                    entity_types.add(label)
        return GraphInfo(
            graph_id=graph_id,
            node_count=len(nodes),
            edge_count=len(edges),
            entity_types=list(entity_types),
        )

    def get_graph_data(self, graph_id: str) -> Dict[str, Any]:
        """Zep 호환 형식의 전체 그래프 데이터를 반환한다."""
        nodes = self.get_all_nodes(graph_id)
        edges = self.get_all_edges(graph_id)

        node_map = {n["uuid"]: n["name"] for n in nodes}

        nodes_data = []
        for node in nodes:
            nodes_data.append({
                "uuid": node["uuid"],
                "name": node["name"],
                "labels": node["labels"],
                "summary": node["summary"],
                "attributes": node["attributes"],
                "created_at": None,
            })

        edges_data = []
        for edge in edges:
            edges_data.append({
                "uuid": "",
                "name": edge["name"],
                "fact": edge["fact"],
                "fact_type": edge["name"],
                "source_node_uuid": edge["source_node_uuid"],
                "target_node_uuid": edge["target_node_uuid"],
                "source_node_name": node_map.get(edge["source_node_uuid"], ""),
                "target_node_name": node_map.get(edge["target_node_uuid"], ""),
                "attributes": {},
                "created_at": edge.get("created_at"),
                "valid_at": None,
                "invalid_at": None,
                "expired_at": None,
                "episodes": [],
            })

        return {
            "graph_id": graph_id,
            "nodes": nodes_data,
            "edges": edges_data,
            "node_count": len(nodes_data),
            "edge_count": len(edges_data),
        }

    # ------------------------------------------------------------------
    # 삭제
    # ------------------------------------------------------------------

    def delete_graph(self, graph_id: str):
        """지정 graph_id에 속하는 엣지와 노드를 모두 삭제한다."""
        conn = self.get_connection()
        # 엣지 먼저 삭제
        conn.execute(
            "MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity) "
            "WHERE r.graph_id = $gid DELETE r",
            {"gid": graph_id},
        )
        conn.execute(
            "MATCH (n:Entity) WHERE n.graph_id = $gid DELETE n",
            {"gid": graph_id},
        )

    # ------------------------------------------------------------------
    # 엔터티 필터링
    # ------------------------------------------------------------------

    def filter_defined_entities(
        self,
        graph_id: str,
        defined_entity_types: Optional[List[str]] = None,
        enrich_with_edges: bool = True,
    ) -> FilteredEntities:
        """사전 정의 타입에 맞는 엔터티를 필터링한다."""
        all_nodes = self.get_all_nodes(graph_id)
        all_edges = self.get_all_edges(graph_id) if enrich_with_edges else []
        node_map = {n["uuid"]: n for n in all_nodes}

        filtered: List[EntityNode] = []
        types_found: Set[str] = set()

        for node in all_nodes:
            labels = node.get("labels", [])
            custom_labels = [la for la in labels if la not in ["Entity", "Node"]]
            if not custom_labels:
                continue

            if defined_entity_types:
                matching = [la for la in custom_labels if la in defined_entity_types]
                if not matching:
                    continue
                entity_type = matching[0]
            else:
                entity_type = custom_labels[0]

            types_found.add(entity_type)

            entity = EntityNode(
                uuid=node["uuid"],
                name=node["name"],
                labels=labels,
                summary=node["summary"],
                attributes=node["attributes"],
            )

            if enrich_with_edges:
                related_edges: List[Dict[str, Any]] = []
                related_node_uuids: Set[str] = set()

                for edge in all_edges:
                    if edge["source_node_uuid"] == node["uuid"]:
                        related_edges.append({
                            "direction": "outgoing",
                            "edge_name": edge["name"],
                            "fact": edge["fact"],
                            "target_node_uuid": edge["target_node_uuid"],
                        })
                        related_node_uuids.add(edge["target_node_uuid"])
                    elif edge["target_node_uuid"] == node["uuid"]:
                        related_edges.append({
                            "direction": "incoming",
                            "edge_name": edge["name"],
                            "fact": edge["fact"],
                            "source_node_uuid": edge["source_node_uuid"],
                        })
                        related_node_uuids.add(edge["source_node_uuid"])

                entity.related_edges = related_edges
                entity.related_nodes = [
                    {
                        "uuid": u,
                        "name": node_map[u]["name"],
                        "labels": node_map[u]["labels"],
                        "summary": node_map[u].get("summary", ""),
                    }
                    for u in related_node_uuids
                    if u in node_map
                ]

            filtered.append(entity)

        return FilteredEntities(
            entities=filtered,
            entity_types=types_found,
            total_count=len(all_nodes),
            filtered_count=len(filtered),
        )

    # ------------------------------------------------------------------
    # 단일 엔터티 조회
    # ------------------------------------------------------------------

    def get_entity_with_context(
        self, graph_id: str, entity_uuid: str
    ) -> Optional[EntityNode]:
        """단일 엔터티와 연관 엣지/노드 컨텍스트를 반환한다."""
        conn = self.get_connection()
        result = conn.execute(
            "MATCH (n:Entity) WHERE n.uuid = $uuid AND n.graph_id = $gid "
            "RETURN n.uuid, n.name, n.label, n.summary, n.attributes",
            {"uuid": entity_uuid, "gid": graph_id},
        )
        if not result.has_next():
            return None

        row = result.get_next()
        entity = EntityNode(
            uuid=row[0],
            name=row[1],
            labels=[row[2], "Entity"] if row[2] else ["Entity"],
            summary=row[3] or "",
            attributes=json.loads(row[4]) if row[4] else {},
        )

        # 연관 엣지/노드 정보
        all_edges = self.get_all_edges(graph_id)
        all_nodes = self.get_all_nodes(graph_id)
        node_map = {n["uuid"]: n for n in all_nodes}

        related_edges: List[Dict[str, Any]] = []
        related_node_uuids: Set[str] = set()

        for edge in all_edges:
            if edge["source_node_uuid"] == entity_uuid:
                related_edges.append({
                    "direction": "outgoing",
                    "edge_name": edge["name"],
                    "fact": edge["fact"],
                    "target_node_uuid": edge["target_node_uuid"],
                })
                related_node_uuids.add(edge["target_node_uuid"])
            elif edge["target_node_uuid"] == entity_uuid:
                related_edges.append({
                    "direction": "incoming",
                    "edge_name": edge["name"],
                    "fact": edge["fact"],
                    "source_node_uuid": edge["source_node_uuid"],
                })
                related_node_uuids.add(edge["source_node_uuid"])

        entity.related_edges = related_edges
        entity.related_nodes = [
            {
                "uuid": u,
                "name": node_map[u]["name"],
                "labels": node_map[u]["labels"],
                "summary": node_map[u].get("summary", ""),
            }
            for u in related_node_uuids
            if u in node_map
        ]
        return entity

    def get_entities_by_type(
        self,
        graph_id: str,
        entity_type: str,
        enrich_with_edges: bool = True,
    ) -> List[EntityNode]:
        """지정 타입의 엔터티를 모두 조회한다."""
        result = self.filter_defined_entities(
            graph_id=graph_id,
            defined_entity_types=[entity_type],
            enrich_with_edges=enrich_with_edges,
        )
        return result.entities

    # ------------------------------------------------------------------
    # 컨텍스트 검색
    # ------------------------------------------------------------------

    def search_entity_context(
        self, graph_id: str, entity_name: str
    ) -> Dict[str, Any]:
        """엔터티 이름으로 관련 사실 및 컨텍스트를 검색한다."""
        conn = self.get_connection()
        facts: List[str] = []
        node_summaries: Set[str] = set()

        # 나가는 엣지
        result = conn.execute(
            "MATCH (n:Entity)-[r:RELATES_TO]->(m:Entity) "
            "WHERE n.graph_id = $gid AND n.name = $name "
            "RETURN r.fact, m.name, m.summary",
            {"gid": graph_id, "name": entity_name},
        )
        while result.has_next():
            row = result.get_next()
            if row[0]:
                facts.append(row[0])
            if row[1] and row[1] != entity_name:
                node_summaries.add(f"엔터티: {row[1]}")
            if row[2]:
                node_summaries.add(row[2])

        # 들어오는 엣지
        result = conn.execute(
            "MATCH (m:Entity)-[r:RELATES_TO]->(n:Entity) "
            "WHERE n.graph_id = $gid AND n.name = $name "
            "RETURN r.fact, m.name, m.summary",
            {"gid": graph_id, "name": entity_name},
        )
        while result.has_next():
            row = result.get_next()
            if row[0]:
                facts.append(row[0])
            if row[1] and row[1] != entity_name:
                node_summaries.add(f"엔터티: {row[1]}")
            if row[2]:
                node_summaries.add(row[2])

        # 컨텍스트 문자열 구축
        context_parts = []
        if facts:
            context_parts.append(
                "사실정보:\n" + "\n".join(f"- {f}" for f in facts[:20])
            )
        if node_summaries:
            context_parts.append(
                "엔터티:\n" + "\n".join(f"- {s}" for s in list(node_summaries)[:10])
            )

        return {
            "facts": facts,
            "node_summaries": list(node_summaries),
            "context": "\n\n".join(context_parts),
        }
