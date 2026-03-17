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

    # ------------------------------------------------------------------
    # 그래프 빌드 (kg-gen 통합)
    # ------------------------------------------------------------------

    def build_graph(
        self,
        text: str,
        ontology: Dict[str, Any],
        graph_name: str = "MiroFish Graph",
        chunk_size: int = 5000,
        progress_callback=None,
    ) -> str:
        """
        텍스트에서 지식 그래프를 생성하고 Kuzu에 저장한다.

        Flow:
        1. graph_id 생성
        2. TextProcessor로 텍스트 분할
        3. 각 청크에 대해 kg.generate() 호출
        4. kg.aggregate()로 병합
        5. kg.cluster()로 엔터티 통합
        6. Kuzu에 Entity 노드 + RELATES_TO 엣지 삽입

        Returns: graph_id
        """
        import uuid as uuid_mod

        graph_id = f"mirofish_{uuid_mod.uuid4().hex[:16]}"

        def report(msg, ratio):
            if progress_callback:
                progress_callback(msg, ratio)

        # 1. 텍스트 분할
        report("텍스트 분할 중...", 0.05)
        chunks = self._split_text(text, chunk_size=chunk_size, overlap=50)
        if not chunks:
            chunks = [text]
        report(f"{len(chunks)}개 청크로 분할 완료", 0.10)

        # 2. 온톨로지에서 컨텍스트 문자열 생성
        context_str = self._ontology_to_context(ontology)

        # 3. 청크별 그래프 생성
        chunk_graphs = []
        for i, chunk in enumerate(chunks):
            report(
                f"청크 {i+1}/{len(chunks)} 처리 중...",
                0.10 + (i / len(chunks)) * 0.50,
            )
            try:
                graph = self.kg.generate(input_data=chunk, context=context_str)
                if graph and (graph.entities or graph.relations):
                    chunk_graphs.append(graph)
            except Exception as e:
                # 로그 남기고 다음 청크 계속 처리
                report(
                    f"청크 {i+1} 처리 실패: {str(e)[:80]}",
                    0.10 + (i / len(chunks)) * 0.50,
                )

        if not chunk_graphs:
            # 모든 청크 실패 시 전체 텍스트로 재시도
            report("청크 처리 실패, 전체 텍스트로 재시도...", 0.60)
            graph = self.kg.generate(
                input_data=text[:chunk_size], context=context_str
            )
            if graph:
                chunk_graphs = [graph]

        # 4. 병합
        report("그래프 병합 중...", 0.65)
        if len(chunk_graphs) > 1:
            aggregated = self.kg.aggregate(chunk_graphs)
        elif chunk_graphs:
            aggregated = chunk_graphs[0]
        else:
            # 엔터티가 없으면 빈 그래프 반환
            report("추출된 엔터티가 없습니다", 0.95)
            return graph_id

        # 5. 클러스터링(엔터티 통합)
        report("엔터티 통합 중...", 0.75)
        try:
            clustered = self.kg.cluster(aggregated, context=context_str)
        except Exception:
            clustered = aggregated

        # 6. Kuzu에 저장
        report("Kuzu에 저장 중...", 0.80)
        self._insert_graph_data(graph_id, clustered, ontology)

        report("그래프 구축 완료", 0.95)
        return graph_id

    @staticmethod
    def _split_text(text: str, chunk_size: int = 5000, overlap: int = 50) -> List[str]:
        """텍스트를 청크로 분할한다 (TextProcessor 의존 없이)."""
        if not text or not text.strip():
            return []
        if len(text) <= chunk_size:
            return [text]
        chunks: List[str] = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            if end < len(text):
                # 문장 경계에서 분할 시도
                for sep in [".\n", "!\n", "?\n", "\n\n", ". ", "! ", "? ", ".", "!", "?"]:
                    last_sep = text[start:end].rfind(sep)
                    if last_sep > chunk_size // 2:
                        end = start + last_sep + len(sep)
                        break
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            start = end - overlap if end < len(text) else end
        return chunks

    def _ontology_to_context(self, ontology: Dict[str, Any]) -> str:
        """온톨로지 dict를 kg-gen 컨텍스트 문자열로 변환한다."""
        parts = []
        entity_types = ontology.get("entity_types", [])
        if entity_types:
            names = [et.get("name", "") for et in entity_types if et.get("name")]
            if names:
                parts.append(
                    f"Focus on extracting these entity types: {', '.join(names)}"
                )
        edge_types = ontology.get("edge_types", [])
        if edge_types:
            names = [et.get("name", "") for et in edge_types if et.get("name")]
            if names:
                parts.append(
                    f"Look for these relationship types: {', '.join(names)}"
                )
        return ". ".join(parts) if parts else ""

    def _insert_graph_data(
        self, graph_id: str, graph, ontology: Dict[str, Any]
    ):
        """kg-gen 그래프 출력을 Kuzu에 삽입한다."""
        import uuid as uuid_mod
        from datetime import datetime

        conn = self.get_connection()
        entity_types = {
            et.get("name", "").lower(): et.get("name", "")
            for et in ontology.get("entity_types", [])
        }

        # 엔터티 이름 → UUID 매핑
        entity_uuid_map: Dict[str, str] = {}

        for entity_name in graph.entities or set():
            entity_uuid = uuid_mod.uuid4().hex[:16]
            entity_uuid_map[entity_name] = entity_uuid

            # 온톨로지 타입 매칭 시도
            label = "Entity"
            entity_lower = entity_name.lower()
            for type_lower, type_orig in entity_types.items():
                if type_lower in entity_lower or entity_lower in type_lower:
                    label = type_orig
                    break

            conn.execute(
                "CREATE (e:Entity {uuid: $uuid, graph_id: $gid, name: $name, "
                "label: $label, summary: $summary, attributes: $attrs})",
                {
                    "uuid": entity_uuid,
                    "gid": graph_id,
                    "name": entity_name,
                    "label": label,
                    "summary": "",
                    "attrs": "{}",
                },
            )

        # 관계를 엣지로 삽입
        now = datetime.now().isoformat()
        for relation in graph.relations or set():
            if len(relation) != 3:
                continue
            src_name, rel_name, tgt_name = relation
            src_uuid = entity_uuid_map.get(src_name)
            tgt_uuid = entity_uuid_map.get(tgt_name)
            if not src_uuid or not tgt_uuid:
                continue
            fact = f"{src_name} {rel_name} {tgt_name}"
            conn.execute(
                "MATCH (a:Entity {uuid: $src}), (b:Entity {uuid: $tgt}) "
                "CREATE (a)-[:RELATES_TO {relation: $rel, fact: $fact, "
                "graph_id: $gid, created_at: $ts}]->(b)",
                {
                    "src": src_uuid,
                    "tgt": tgt_uuid,
                    "rel": rel_name,
                    "fact": fact,
                    "gid": graph_id,
                    "ts": now,
                },
            )

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
