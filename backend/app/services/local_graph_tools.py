"""
로컬 그래프 도구 서비스.
ZepToolsService를 대체하여 LocalGraphService 기반으로 그래프 검색, 분석 도구를 제공한다.

도구 목록:
1. InsightForge (심층 분석) - LLM 하위 질문 생성 + Cypher 검색
2. PanoramaSearch (전역 탐색) - 전체 노드/엣지 스캔
3. QuickSearch (빠른 검색) - 키워드 기반 Cypher CONTAINS 검색
4. interview_agents (에이전트 인터뷰) - OASIS IPC 기반 인터뷰
"""

import json
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from ..utils.logger import get_logger

logger = get_logger('mirofish.local_graph_tools')


@dataclass
class SearchResult:
    """검색 결과."""
    facts: List[str]
    edges: List[Dict[str, Any]]
    nodes: List[Dict[str, Any]]
    query: str
    total_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "facts": self.facts,
            "edges": self.edges,
            "nodes": self.nodes,
            "query": self.query,
            "total_count": self.total_count
        }

    def to_text(self) -> str:
        """텍스트 형식으로 변환, LLM 입력용."""
        text_parts = [f"검색조회: {self.query}", f" {self.total_count}건정보"]

        if self.facts:
            text_parts.append("\n### 사실:")
            for i, fact in enumerate(self.facts, 1):
                text_parts.append(f"{i}. {fact}")

        return "\n".join(text_parts)


@dataclass
class NodeInfo:
    """노드 정보."""
    uuid: str
    name: str
    labels: List[str]
    summary: str
    attributes: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "labels": self.labels,
            "summary": self.summary,
            "attributes": self.attributes
        }

    def to_text(self) -> str:
        """텍스트 형식."""
        entity_type = next((l for l in self.labels if l not in ["Entity", "Node"]), "타입")
        return f"엔터티: {self.name} (타입: {entity_type})\n요약: {self.summary}"


@dataclass
class EdgeInfo:
    """엣지 정보."""
    uuid: str
    name: str
    fact: str
    source_node_uuid: str
    target_node_uuid: str
    source_node_name: Optional[str] = None
    target_node_name: Optional[str] = None
    # 시간 정보 (로컬 스택에서는 항상 None)
    created_at: Optional[str] = None
    valid_at: Optional[str] = None      # Always None in local stack
    invalid_at: Optional[str] = None    # Always None
    expired_at: Optional[str] = None    # Always None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "fact": self.fact,
            "source_node_uuid": self.source_node_uuid,
            "target_node_uuid": self.target_node_uuid,
            "source_node_name": self.source_node_name,
            "target_node_name": self.target_node_name,
            "created_at": self.created_at,
            "valid_at": self.valid_at,
            "invalid_at": self.invalid_at,
            "expired_at": self.expired_at
        }

    def to_text(self, include_temporal: bool = False) -> str:
        """텍스트 형식."""
        source = self.source_node_name or self.source_node_uuid[:8]
        target = self.target_node_name or self.target_node_uuid[:8]
        base_text = f"관계: {source} --[{self.name}]--> {target}\n사실: {self.fact}"

        if include_temporal:
            valid_at = self.valid_at or ""
            invalid_at = self.invalid_at or ""
            base_text += f"\n: {valid_at} - {invalid_at}"
            if self.expired_at:
                base_text += f" (만료: {self.expired_at})"

        return base_text

    @property
    def is_expired(self) -> bool:
        """로컬 스택에서는 만료 개념이 없으므로 항상 False."""
        return False

    @property
    def is_invalid(self) -> bool:
        """로컬 스택에서는 무효 개념이 없으므로 항상 False."""
        return False


@dataclass
class InsightForgeResult:
    """
    심층 분석 결과 (InsightForge).
    하위 질문 생성, 검색, 분석 통합.
    """
    query: str
    simulation_requirement: str
    sub_queries: List[str]

    # 검색 결과
    semantic_facts: List[str] = field(default_factory=list)
    entity_insights: List[Dict[str, Any]] = field(default_factory=list)
    relationship_chains: List[str] = field(default_factory=list)

    # 통계 정보
    total_facts: int = 0
    total_entities: int = 0
    total_relationships: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "simulation_requirement": self.simulation_requirement,
            "sub_queries": self.sub_queries,
            "semantic_facts": self.semantic_facts,
            "entity_insights": self.entity_insights,
            "relationship_chains": self.relationship_chains,
            "total_facts": self.total_facts,
            "total_entities": self.total_entities,
            "total_relationships": self.total_relationships
        }

    def to_text(self) -> str:
        """상세 텍스트, LLM 보고서 생성용."""
        text_parts = [
            f"## 분석",
            f"분석질문: {self.query}",
            f": {self.simulation_requirement}",
            f"\n### ",
            f"- 사실: {self.total_facts}",
            f"- 엔터티: {self.total_entities}",
            f"- 관계 체인: {self.total_relationships}"
        ]

        # 하위 질문
        if self.sub_queries:
            text_parts.append(f"\n### 분석질문")
            for i, sq in enumerate(self.sub_queries, 1):
                text_parts.append(f"{i}. {sq}")

        # 핵심 사실
        if self.semantic_facts:
            text_parts.append(f"\n### [핵심사실](보고서진행 중)")
            for i, fact in enumerate(self.semantic_facts, 1):
                text_parts.append(f'{i}. "{fact}"')

        # 엔터티 인사이트
        if self.entity_insights:
            text_parts.append(f"\n### [엔터티]")
            for entity in self.entity_insights:
                text_parts.append(f"- **{entity.get('name', '')}** ({entity.get('type', '엔터티')})")
                if entity.get('summary'):
                    text_parts.append(f"  요약: \"{entity.get('summary')}\"")
                if entity.get('related_facts'):
                    text_parts.append(f"  사실: {len(entity.get('related_facts', []))}")

        # 관계 체인
        if self.relationship_chains:
            text_parts.append(f"\n### [관계 체인]")
            for chain in self.relationship_chains:
                text_parts.append(f"- {chain}")

        return "\n".join(text_parts)


@dataclass
class PanoramaResult:
    """
    전역 탐색 결과 (Panorama).
    전체 노드/엣지 정보 및 사실 분류.
    """
    query: str

    # 노드/엣지
    all_nodes: List[NodeInfo] = field(default_factory=list)
    all_edges: List[EdgeInfo] = field(default_factory=list)
    # 현재 유효 사실
    active_facts: List[str] = field(default_factory=list)
    # 과거/만료 사실 (로컬 스택에서는 항상 빈 리스트)
    historical_facts: List[str] = field(default_factory=list)

    # 통계
    total_nodes: int = 0
    total_edges: int = 0
    active_count: int = 0
    historical_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "all_nodes": [n.to_dict() for n in self.all_nodes],
            "all_edges": [e.to_dict() for e in self.all_edges],
            "active_facts": self.active_facts,
            "historical_facts": self.historical_facts,
            "total_nodes": self.total_nodes,
            "total_edges": self.total_edges,
            "active_count": self.active_count,
            "historical_count": self.historical_count
        }

    def to_text(self) -> str:
        """전역 탐색 결과 텍스트 (현재/과거 구분)."""
        text_parts = [
            f"## 검색()",
            f"조회: {self.query}",
            f"\n### 정보",
            f"- 노드: {self.total_nodes}",
            f"- 엣지: {self.total_edges}",
            f"- 현재유효사실: {self.active_count}",
            f"- 과거/만료사실: {self.historical_count}"
        ]

        # 현재 유효 사실
        if self.active_facts:
            text_parts.append(f"\n### [현재유효사실](시뮬레이션)")
            for i, fact in enumerate(self.active_facts, 1):
                text_parts.append(f'{i}. "{fact}"')

        # 과거/만료 사실
        if self.historical_facts:
            text_parts.append(f"\n### [과거/만료사실]()")
            for i, fact in enumerate(self.historical_facts, 1):
                text_parts.append(f'{i}. "{fact}"')

        # 엔터티 목록
        if self.all_nodes:
            text_parts.append(f"\n### [엔터티]")
            for node in self.all_nodes:
                entity_type = next((l for l in node.labels if l not in ["Entity", "Node"]), "엔터티")
                text_parts.append(f"- **{node.name}** ({entity_type})")

        return "\n".join(text_parts)


@dataclass
class AgentInterview:
    """Agent 인터뷰 단건."""
    agent_name: str
    agent_role: str
    agent_bio: str
    question: str
    response: str
    key_quotes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "agent_role": self.agent_role,
            "agent_bio": self.agent_bio,
            "question": self.question,
            "response": self.response,
            "key_quotes": self.key_quotes
        }

    def to_text(self) -> str:
        text = f"**{self.agent_name}** ({self.agent_role})\n"
        text += f"_: {self.agent_bio}_\n\n"
        text += f"**Q:** {self.question}\n\n"
        text += f"**A:** {self.response}\n"
        if self.key_quotes:
            text += "\n**핵심:**\n"
            for quote in self.key_quotes:
                clean_quote = quote.replace('\u201c', '').replace('\u201d', '').replace('"', '')
                clean_quote = clean_quote.replace('\u300c', '').replace('\u300d', '')
                clean_quote = clean_quote.strip()
                while clean_quote and clean_quote[0] in ', ,;;::, .!?\n\r\t ':
                    clean_quote = clean_quote[1:]
                skip = False
                for d in '123456789':
                    if f'\u95ee\u9898{d}' in clean_quote:
                        skip = True
                        break
                if skip:
                    continue
                if len(clean_quote) > 150:
                    dot_pos = clean_quote.find('\u3002', 80)
                    if dot_pos > 0:
                        clean_quote = clean_quote[:dot_pos + 1]
                    else:
                        clean_quote = clean_quote[:147] + "..."
                if clean_quote and len(clean_quote) >= 10:
                    text += f'> "{clean_quote}"\n'
        return text


@dataclass
class InterviewResult:
    """
    인터뷰 결과 (Interview).
    시뮬레이션 Agent 인터뷰 통합.
    """
    interview_topic: str
    interview_questions: List[str]

    # 인터뷰 대상 Agent
    selected_agents: List[Dict[str, Any]] = field(default_factory=list)
    # Agent 인터뷰 기록
    interviews: List[AgentInterview] = field(default_factory=list)

    # 선정 이유
    selection_reasoning: str = ""
    # 인터뷰 요약
    summary: str = ""

    # 통계
    total_agents: int = 0
    interviewed_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "interview_topic": self.interview_topic,
            "interview_questions": self.interview_questions,
            "selected_agents": self.selected_agents,
            "interviews": [i.to_dict() for i in self.interviews],
            "selection_reasoning": self.selection_reasoning,
            "summary": self.summary,
            "total_agents": self.total_agents,
            "interviewed_count": self.interviewed_count
        }

    def to_text(self) -> str:
        """상세 텍스트, LLM 보고서 생성용."""
        text_parts = [
            "## 인터뷰보고서",
            f"**인터뷰주제:** {self.interview_topic}",
            f"**인터뷰인원:** {self.interviewed_count} / {self.total_agents} 시뮬레이션Agent",
            "\n### 인터뷰선정 이유",
            self.selection_reasoning or "(선정)",
            "\n---",
            "\n### 인터뷰기록",
        ]

        if self.interviews:
            for i, interview in enumerate(self.interviews, 1):
                text_parts.append(f"\n#### 인터뷰 #{i}: {interview.agent_name}")
                text_parts.append(interview.to_text())
                text_parts.append("\n---")
        else:
            text_parts.append("(인터뷰)\n\n---")

        text_parts.append("\n### 인터뷰요약")
        text_parts.append(self.summary or "(요약)")

        return "\n".join(text_parts)


class LocalGraphToolsService:
    """
    로컬 그래프 도구 서비스.
    ZepToolsService를 대체하여 LocalGraphService(Kuzu) 기반으로 동작한다.

    [도구 - 주요]
    1. insight_forge - 심층 분석 (LLM 하위 질문 생성 + Cypher 검색)
    2. panorama_search - 전역 탐색 (전체 노드/엣지 스캔)
    3. quick_search - 빠른 검색 (Cypher CONTAINS)
    4. interview_agents - 에이전트 인터뷰 (OASIS IPC)

    [도구 - 보조]
    - get_graph_statistics - 그래프 통계
    - get_entity_summary - 엔터티 요약
    - get_entities_by_type - 타입별 엔터티
    - get_simulation_context - 시뮬레이션 컨텍스트
    """

    def __init__(self, graph_service=None, llm_client=None):
        if graph_service is None:
            from ..config import get_graph_service
            graph_service = get_graph_service()
        self.graph_service = graph_service

        if llm_client is None:
            from ..config import Config
            from ..utils.llm_client import LLMClient
            llm_client = LLMClient(
                api_key=Config.LLM_API_KEY,
                base_url=Config.LLM_BASE_URL,
                model=Config.LLM_MODEL_NAME,
            )
        self._llm_client = llm_client
        logger.info("LocalGraphToolsService 초기화 완료")

    @property
    def llm(self):
        """LLM 클라이언트."""
        return self._llm_client

    # ========== 주요 도구 ==========

    def quick_search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
    ) -> SearchResult:
        """
        키워드 기반 빠른 검색 (Cypher CONTAINS).

        Args:
            graph_id: 그래프 ID
            query: 검색 질의
            limit: 반환 개수 제한

        Returns:
            SearchResult: 검색 결과
        """
        logger.info(f"QuickSearch 검색: graph_id={graph_id}, query={query[:50]}...")

        conn = self.graph_service.get_connection()
        facts = []
        edges = []
        nodes = []

        # 엣지(사실) 검색
        try:
            result = conn.execute(
                "MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity) "
                "WHERE r.graph_id = $gid AND r.fact CONTAINS $kw "
                "RETURN r.fact, a.name, b.name, a.uuid, b.uuid, r.relation "
                "LIMIT $lim",
                {"gid": graph_id, "kw": query, "lim": limit * 2},
            )
            while result.has_next():
                row = result.get_next()
                fact = row[0]
                if fact and fact not in facts:
                    facts.append(fact)
                edges.append({
                    "fact": row[0],
                    "source": row[1],
                    "target": row[2],
                    "source_uuid": row[3],
                    "target_uuid": row[4],
                    "relation": row[5],
                })
        except Exception as e:
            logger.warning(f"엣지 검색 실패: {e}")

        # 엔터티 이름 검색
        try:
            result = conn.execute(
                "MATCH (n:Entity) WHERE n.graph_id = $gid AND n.name CONTAINS $kw "
                "RETURN n.uuid, n.name, n.label, n.summary "
                "LIMIT $lim",
                {"gid": graph_id, "kw": query, "lim": limit},
            )
            while result.has_next():
                row = result.get_next()
                nodes.append({
                    "uuid": row[0],
                    "name": row[1],
                    "label": row[2],
                    "summary": row[3],
                })
        except Exception as e:
            logger.warning(f"노드 검색 실패: {e}")

        logger.info(f"QuickSearch 완료: {len(facts)}건 사실, {len(nodes)}건 노드")
        return SearchResult(
            facts=facts,
            edges=edges,
            nodes=nodes,
            query=query,
            total_count=len(facts) + len(nodes),
        )

    def panorama_search(
        self,
        graph_id: str,
        query: str,
        include_expired: bool = True,
        limit: int = 50,
    ) -> PanoramaResult:
        """
        그래프 전체를 폭넓게 탐색해 현재/과거 사실을 조회한다.
        로컬 스택에서는 모든 사실이 active로 분류된다(만료 개념 없음).

        Args:
            graph_id: 그래프 ID
            query: 검색 질의
            include_expired: 만료/과거 사실 포함 여부 (호환용, 실제로는 무시)
            limit: 반환 개수 제한

        Returns:
            PanoramaResult: 전역 탐색 결과
        """
        logger.info(f"PanoramaSearch 검색: graph_id={graph_id}, query={query[:50]}...")

        all_nodes_data = self.graph_service.get_all_nodes(graph_id)
        all_edges_data = self.graph_service.get_all_edges(graph_id)
        node_map = {n["uuid"]: n["name"] for n in all_nodes_data}

        nodes = [
            NodeInfo(
                uuid=n["uuid"],
                name=n["name"],
                labels=n["labels"],
                summary=n["summary"],
                attributes=n["attributes"],
            )
            for n in all_nodes_data
        ]

        edges = [
            EdgeInfo(
                uuid="",
                name=e["name"],
                fact=e["fact"],
                source_node_uuid=e["source_node_uuid"],
                target_node_uuid=e["target_node_uuid"],
                source_node_name=node_map.get(e["source_node_uuid"]),
                target_node_name=node_map.get(e["target_node_uuid"]),
                created_at=e.get("created_at"),
            )
            for e in all_edges_data
        ]

        # 로컬 스택에서는 모든 사실이 active (is_expired/is_invalid 항상 False)
        active_facts = [e.fact for e in edges if e.fact]

        # 키워드 관련도 정렬
        query_lower = query.lower()
        keywords = [w.strip() for w in query_lower.replace(',', ' ').split() if len(w.strip()) > 1]

        def relevance_score(fact: str) -> int:
            fact_lower = fact.lower()
            score = 0
            if query_lower in fact_lower:
                score += 100
            for kw in keywords:
                if kw in fact_lower:
                    score += 10
            return score

        active_facts.sort(key=relevance_score, reverse=True)

        result = PanoramaResult(
            query=query,
            all_nodes=nodes,
            all_edges=edges,
            active_facts=active_facts[:limit],
            historical_facts=[],  # 로컬 스택에서는 과거 사실 없음
            total_nodes=len(nodes),
            total_edges=len(edges),
            active_count=len(active_facts),
            historical_count=0,
        )

        logger.info(f"PanoramaSearch 완료: {result.active_count}건 유효 사실")
        return result

    def insight_forge(
        self,
        graph_id: str,
        query: str,
        simulation_requirement: str,
        report_context: str = "",
        max_sub_queries: int = 5,
    ) -> InsightForgeResult:
        """
        LLM 하위 질문 생성 + Cypher 검색으로 심층 분석을 수행한다.

        Args:
            graph_id: 그래프 ID
            query: 분석 질문
            simulation_requirement: 시뮬레이션 요구사항
            report_context: 보고서 맥락 (선택)
            max_sub_queries: 하위 질문 최대 수

        Returns:
            InsightForgeResult: 심층 분석 결과
        """
        logger.info(f"InsightForge 분석: {query[:50]}...")

        result = InsightForgeResult(
            query=query,
            simulation_requirement=simulation_requirement,
            sub_queries=[],
        )

        # Step 1: LLM으로 하위 질문 생성
        sub_queries = self._generate_sub_queries(
            query=query,
            simulation_requirement=simulation_requirement,
            report_context=report_context,
            max_queries=max_sub_queries,
        )
        result.sub_queries = sub_queries
        logger.info(f"생성된 {len(sub_queries)}개 하위 질문")

        # Step 2: 하위 질문별 검색
        all_facts = []
        seen_facts = set()
        entity_insights = []

        for sub_query in sub_queries:
            search_result = self.quick_search(graph_id, sub_query)
            for fact in search_result.facts:
                if fact not in seen_facts:
                    all_facts.append(fact)
                    seen_facts.add(fact)
            for node in search_result.nodes:
                entity_insights.append({
                    "name": node.get("name"),
                    "type": node.get("label", "Entity"),
                    "summary": node.get("summary", ""),
                    "related_facts": [],
                })

        # 원래 질문으로도 검색
        main_search = self.quick_search(graph_id, query)
        for fact in main_search.facts:
            if fact not in seen_facts:
                all_facts.append(fact)
                seen_facts.add(fact)

        result.semantic_facts = all_facts
        result.total_facts = len(all_facts)

        # 엔터티 중복 제거
        seen_names = set()
        deduped_insights = []
        for ei in entity_insights:
            name = ei.get("name", "")
            if name and name not in seen_names:
                seen_names.add(name)
                # 관련 사실 매칭
                ei["related_facts"] = [
                    f for f in all_facts if name.lower() in f.lower()
                ]
                deduped_insights.append(ei)

        result.entity_insights = deduped_insights
        result.total_entities = len(deduped_insights)

        # 관계 체인 구성
        relationship_chains = []
        for edge in main_search.edges:
            if isinstance(edge, dict):
                source = edge.get("source", edge.get("source_name", ""))
                target = edge.get("target", edge.get("target_name", ""))
                relation = edge.get("relation", "")
                chain = f"{source} --[{relation}]--> {target}"
                if chain not in relationship_chains:
                    relationship_chains.append(chain)
        result.relationship_chains = relationship_chains
        result.total_relationships = len(relationship_chains)

        logger.info(
            f"InsightForge 완료: {result.total_facts}건 사실, "
            f"{result.total_entities}건 엔터티, {result.total_relationships}건 관계"
        )
        return result

    def _generate_sub_queries(
        self,
        query: str,
        simulation_requirement: str,
        report_context: str = "",
        max_queries: int = 5,
    ) -> List[str]:
        """원 질문을 하위 질문으로 분해해 검색 품질을 높인다."""
        system_prompt = """당신은 검색 질의 분해 전문가입니다.

작업:
1. 원 질문을 분석해 핵심 하위 질문 3~5개를 만드세요.
2. 하위 질문은 서로 중복되지 않아야 합니다.
3. 시뮬레이션 맥락(행위자, 관계, 사건)을 반영하세요.
4. JSON만 반환하세요.

반환 형식:
{"sub_queries": ["질문1", "질문2", "..."]}"""

        user_prompt = f"""시뮬레이션 요구사항:
{simulation_requirement}

{f"보고서 맥락: {report_context[:500]}" if report_context else ""}

원 질문:
{query}

최대 {max_queries}개의 하위 질문을 생성하세요."""

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )

            sub_queries = response.get("sub_queries", [])
            return [str(sq) for sq in sub_queries[:max_queries]]

        except Exception as e:
            logger.warning(f"하위 질문 생성 실패: {str(e)}. 원 질문 기반 폴백을 사용합니다.")
            return [
                query,
                f"{query}의 핵심 근거는 무엇인가?",
                f"{query}와 관련된 주요 행위자는 누구인가?",
                f"{query}가 시뮬레이션에 미친 영향은 무엇인가?"
            ][:max_queries]

    def interview_agents(
        self,
        simulation_id: str,
        interview_requirement: str,
        simulation_requirement: str = "",
        max_agents: int = 5,
        custom_questions: List[str] = None,
    ) -> InterviewResult:
        """
        OASIS 인터뷰 API를 호출해 시뮬레이션 에이전트를 인터뷰한다.
        이 기능은 Zep 독립적이며, OASIS IPC를 통해 동작한다.

        Args:
            simulation_id: 시뮬레이션 ID
            interview_requirement: 인터뷰 목표/주제
            simulation_requirement: 시뮬레이션 요구사항 (선택)
            max_agents: 최대 인터뷰 대상 수
            custom_questions: 사용자 지정 질문 목록 (선택)

        Returns:
            InterviewResult: 인터뷰 결과
        """
        from .simulation_runner import SimulationRunner

        logger.info(f"InterviewAgents 인터뷰(API): {interview_requirement[:50]}...")

        result = InterviewResult(
            interview_topic=interview_requirement,
            interview_questions=custom_questions or [],
        )

        # Step 1: 프로필 파일 로드
        profiles = self._load_agent_profiles(simulation_id)

        if not profiles:
            logger.warning(f"시뮬레이션 {simulation_id} 프로필 파일 없음")
            result.summary = "인터뷰할 에이전트 프로필 파일을 찾을 수 없습니다."
            return result

        result.total_agents = len(profiles)
        logger.info(f"로드 {len(profiles)}개 Agent 프로필")

        # Step 2: LLM으로 인터뷰 대상 Agent 선정
        selected_agents, selected_indices, selection_reasoning = self._select_agents_for_interview(
            profiles=profiles,
            interview_requirement=interview_requirement,
            simulation_requirement=simulation_requirement,
            max_agents=max_agents,
        )

        result.selected_agents = selected_agents
        result.selection_reasoning = selection_reasoning
        logger.info(f"선정 {len(selected_agents)}개 Agent 인터뷰: {selected_indices}")

        # Step 3: 인터뷰 질문 생성
        if not result.interview_questions:
            result.interview_questions = self._generate_interview_questions(
                interview_requirement=interview_requirement,
                simulation_requirement=simulation_requirement,
                selected_agents=selected_agents,
            )
            logger.info(f"생성 {len(result.interview_questions)}개 인터뷰 질문")

        # 질문 결합
        combined_prompt = "\n".join(
            [f"{i+1}. {q}" for i, q in enumerate(result.interview_questions)]
        )

        INTERVIEW_PROMPT_PREFIX = (
            "아래 질문에 인터뷰 형식으로 답변해 주세요.\n"
            "작성 규칙:\n"
            "1. 도구 호출 JSON은 출력하지 않습니다.\n"
            "2. Markdown 헤더(#, ##, ###)는 사용하지 않습니다.\n"
            "3. 질문 번호(예: '질문1:')는 출력하지 않습니다.\n"
            "4. 각 질문마다 2~3문장으로 구체적으로 답하세요.\n\n"
        )
        optimized_prompt = f"{INTERVIEW_PROMPT_PREFIX}{combined_prompt}"

        # Step 4: 인터뷰 API 호출
        try:
            interviews_request = []
            for agent_idx in selected_indices:
                interviews_request.append({
                    "agent_id": agent_idx,
                    "prompt": optimized_prompt,
                })

            logger.info(f"인터뷰 API 호출: {len(interviews_request)}개 Agent")

            api_result = SimulationRunner.interview_agents_batch(
                simulation_id=simulation_id,
                interviews=interviews_request,
                platform=None,
                timeout=180.0,
            )

            logger.info(
                f"인터뷰 API 반환: {api_result.get('interviews_count', 0)}건, "
                f"success={api_result.get('success')}"
            )

            if not api_result.get("success", False):
                error_msg = api_result.get("error", "오류")
                logger.warning(f"인터뷰 API 실패: {error_msg}")
                result.summary = f"인터뷰 API 호출에 실패했습니다: {error_msg}. OASIS 시뮬레이션 상태를 확인해 주세요."
                return result

            # Step 5: API 결과 파싱
            import re
            api_data = api_result.get("result", {})
            results_dict = api_data.get("results", {}) if isinstance(api_data, dict) else {}

            for i, agent_idx in enumerate(selected_indices):
                agent = selected_agents[i]
                agent_name = agent.get("realname", agent.get("username", f"Agent_{agent_idx}"))
                agent_role = agent.get("profession", "")
                agent_bio = agent.get("bio", "")

                twitter_result = results_dict.get(f"twitter_{agent_idx}", {})
                reddit_result = results_dict.get(f"reddit_{agent_idx}", {})

                twitter_response = twitter_result.get("response", "")
                reddit_response = reddit_result.get("response", "")

                twitter_response = self._clean_tool_call_response(twitter_response)
                reddit_response = self._clean_tool_call_response(reddit_response)

                twitter_text = twitter_response if twitter_response else "(플랫폼 없음)"
                reddit_text = reddit_response if reddit_response else "(플랫폼 없음)"
                response_text = f"[Twitter 플랫폼]\n{twitter_text}\n\n[Reddit 플랫폼]\n{reddit_text}"

                combined_responses = f"{twitter_response} {reddit_response}"

                clean_text = re.sub(r'#{1,6}\s+', '', combined_responses)
                clean_text = re.sub(r'\{[^}]*tool_name[^}]*\}', '', clean_text)
                clean_text = re.sub(r'[*_`|>~\-]{2,}', '', clean_text)
                clean_text = re.sub(r'질문\d+:\s*', '', clean_text)
                clean_text = re.sub(r'\[[^\]]+\]', '', clean_text)

                sentences = re.split(r'[.!?]', clean_text)
                meaningful = [
                    s.strip() for s in sentences
                    if 20 <= len(s.strip()) <= 150
                    and not re.match(r'^[\s\W,:;]+', s.strip())
                    and not s.strip().startswith(('{', '질문'))
                ]
                meaningful.sort(key=len, reverse=True)
                key_quotes = [s + "." for s in meaningful[:3]]

                if not key_quotes:
                    paired = re.findall(r'\u201c([^\u201c\u201d]{15,100})\u201d', clean_text)
                    paired += re.findall(r'\u300c([^\u300c\u300d]{15,100})\u300d', clean_text)
                    key_quotes = [q for q in paired if not re.match(r'^[,:;]+', q)][:3]

                interview = AgentInterview(
                    agent_name=agent_name,
                    agent_role=agent_role,
                    agent_bio=agent_bio[:1000],
                    question=combined_prompt,
                    response=response_text,
                    key_quotes=key_quotes[:5],
                )
                result.interviews.append(interview)

            result.interviewed_count = len(result.interviews)

        except ValueError as e:
            logger.warning(f"인터뷰 API 호출 실패 (시뮬레이션 미실행?): {e}")
            result.summary = f"인터뷰에 실패했습니다: {str(e)}. 시뮬레이션이 실행 중인지 확인해 주세요."
            return result
        except Exception as e:
            logger.error(f"인터뷰 API 호출 오류: {e}")
            import traceback
            logger.error(traceback.format_exc())
            result.summary = f"인터뷰 처리 중 오류가 발생했습니다: {str(e)}"
            return result

        # Step 6: 인터뷰 요약 생성
        if result.interviews:
            result.summary = self._generate_interview_summary(
                interviews=result.interviews,
                interview_requirement=interview_requirement,
            )

        logger.info(f"InterviewAgents 완료: 인터뷰 {result.interviewed_count}개 Agent")
        return result

    @staticmethod
    def _clean_tool_call_response(response: str) -> str:
        """에이전트 응답에 섞인 도구 호출 JSON을 텍스트로 정리한다."""
        if not response or not response.strip().startswith('{'):
            return response
        text = response.strip()
        if 'tool_name' not in text[:80]:
            return response
        import re as _re
        try:
            data = json.loads(text)
            if isinstance(data, dict) and 'arguments' in data:
                for key in ('content', 'text', 'body', 'message', 'reply'):
                    if key in data['arguments']:
                        return str(data['arguments'][key])
        except (json.JSONDecodeError, KeyError, TypeError):
            match = _re.search(r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
            if match:
                return match.group(1).replace('\\n', '\n').replace('\\"', '"')
        return response

    # ========== 보조 도구 ==========

    def get_graph_statistics(self, graph_id: str) -> Dict[str, Any]:
        """그래프 통계 정보를 반환한다."""
        logger.info(f"그래프 {graph_id} 통계 조회...")
        info = self.graph_service.get_graph_info(graph_id)
        return {
            "graph_id": graph_id,
            "total_nodes": info.node_count,
            "total_edges": info.edge_count,
            "entity_types": {t: 0 for t in info.entity_types},  # 호환용
        }

    def get_entity_summary(
        self,
        graph_id: str,
        entity_name: str,
    ) -> Dict[str, Any]:
        """엔터티 관계 요약을 반환한다."""
        logger.info(f"엔터티 {entity_name} 관계 요약...")

        # 이름으로 노드 검색
        nodes = self.graph_service.get_all_nodes(graph_id)
        entity_node = None
        for node in nodes:
            if node["name"].lower() == entity_name.lower():
                entity_node = node
                break

        # 관련 사실 검색
        search_result = self.quick_search(graph_id, entity_name)

        return {
            "entity_name": entity_name,
            "entity_info": entity_node,
            "related_facts": search_result.facts,
            "related_edges": search_result.edges,
            "total_relations": len(search_result.edges),
        }

    def get_entities_by_type(
        self,
        graph_id: str,
        entity_type: str,
    ) -> List[NodeInfo]:
        """타입별 엔터티를 반환한다."""
        logger.info(f"타입 {entity_type} 엔터티 조회...")
        entities = self.graph_service.get_entities_by_type(graph_id, entity_type)
        return [
            NodeInfo(
                uuid=e.uuid,
                name=e.name,
                labels=e.labels,
                summary=e.summary,
                attributes=e.attributes,
            )
            for e in entities
        ]

    def get_simulation_context(
        self,
        graph_id: str,
        simulation_requirement: str,
        limit: int = 30,
    ) -> Dict[str, Any]:
        """시뮬레이션 컨텍스트 정보를 반환한다."""
        logger.info(f"시뮬레이션 컨텍스트: {simulation_requirement[:50]}...")

        # 관련 사실 검색
        search_result = self.quick_search(graph_id, simulation_requirement)

        # 그래프 통계
        stats = self.get_graph_statistics(graph_id)

        # 타입이 있는 엔터티만 추출
        all_nodes = self.graph_service.get_all_nodes(graph_id)
        entities = []
        for node in all_nodes:
            custom_labels = [l for l in node.get("labels", []) if l not in ["Entity", "Node"]]
            if custom_labels:
                entities.append({
                    "name": node["name"],
                    "type": custom_labels[0],
                    "summary": node.get("summary", ""),
                })

        return {
            "simulation_requirement": simulation_requirement,
            "related_facts": search_result.facts,
            "graph_statistics": stats,
            "entities": entities[:limit],
            "total_entities": len(entities),
        }

    # ========== 내부 헬퍼 (인터뷰) ==========

    def _load_agent_profiles(self, simulation_id: str) -> List[Dict[str, Any]]:
        """시뮬레이션 디렉터리에서 에이전트 프로필 파일을 로드한다."""
        import os
        import csv

        sim_dir = os.path.join(
            os.path.dirname(__file__),
            f'../../uploads/simulations/{simulation_id}',
        )

        profiles = []

        # Reddit JSON 프로필
        reddit_profile_path = os.path.join(sim_dir, "reddit_profiles.json")
        if os.path.exists(reddit_profile_path):
            try:
                with open(reddit_profile_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        profiles = data
                    elif isinstance(data, dict) and "profiles" in data:
                        profiles = data["profiles"]
            except Exception as e:
                logger.warning(f"Reddit 프로필 로드 실패: {e}")

        # CSV 프로필
        if not profiles:
            csv_path = os.path.join(sim_dir, "agent_profiles.csv")
            if os.path.exists(csv_path):
                try:
                    with open(csv_path, 'r', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        profiles = list(reader)
                except Exception as e:
                    logger.warning(f"CSV 프로필 로드 실패: {e}")

        return profiles

    def _select_agents_for_interview(
        self,
        profiles: List[Dict[str, Any]],
        interview_requirement: str,
        simulation_requirement: str,
        max_agents: int = 5,
    ):
        """LLM으로 인터뷰 대상 에이전트를 선정한다."""
        profiles_summary = []
        for i, p in enumerate(profiles):
            name = p.get("realname", p.get("username", f"Agent_{i}"))
            role = p.get("profession", "")
            bio_short = (p.get("bio", "") or "")[:200]
            profiles_summary.append(f"{i}: {name} ({role}) - {bio_short}")

        system_prompt = """에이전트 인터뷰 대상을 선정하세요.
JSON만 반환하세요.
{"selected_indices": [0, 1, 2], "reasoning": "선정 이유"}"""

        user_prompt = f"""인터뷰 주제: {interview_requirement}
시뮬레이션: {simulation_requirement}
에이전트 목록:
{chr(10).join(profiles_summary[:30])}
최대 {max_agents}명을 선정하세요."""

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
            )
            indices = response.get("selected_indices", list(range(min(max_agents, len(profiles)))))
            reasoning = response.get("reasoning", "")
        except Exception:
            indices = list(range(min(max_agents, len(profiles))))
            reasoning = "LLM 선정 실패로 상위 에이전트를 선택했습니다."

        selected = []
        valid_indices = []
        for idx in indices[:max_agents]:
            if 0 <= idx < len(profiles):
                selected.append(profiles[idx])
                valid_indices.append(idx)

        return selected, valid_indices, reasoning

    def _generate_interview_questions(
        self,
        interview_requirement: str,
        simulation_requirement: str,
        selected_agents: List[Dict[str, Any]],
    ) -> List[str]:
        """인터뷰 질문을 LLM으로 생성한다."""
        system_prompt = """인터뷰 질문을 3~5개 생성하세요.
JSON만 반환하세요.
{"questions": ["질문1", "질문2", ...]}"""

        agent_names = [
            a.get("realname", a.get("username", "Agent"))
            for a in selected_agents[:5]
        ]

        user_prompt = f"""인터뷰 주제: {interview_requirement}
시뮬레이션: {simulation_requirement}
대상 에이전트: {', '.join(agent_names)}"""

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
            )
            return response.get("questions", [interview_requirement])[:5]
        except Exception:
            return [interview_requirement]

    def _generate_interview_summary(
        self,
        interviews: List[AgentInterview],
        interview_requirement: str,
    ) -> str:
        """인터뷰 결과를 요약한다."""
        interview_texts = []
        for iv in interviews:
            interview_texts.append(f"- {iv.agent_name}: {iv.response[:300]}")

        system_prompt = "인터뷰 결과를 3~5문장으로 요약하세요."
        user_prompt = f"""인터뷰 주제: {interview_requirement}
인터뷰 결과:
{chr(10).join(interview_texts)}"""

        try:
            return self.llm.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=500,
            )
        except Exception as e:
            logger.warning(f"인터뷰 요약 생성 실패: {e}")
            return f"{len(interviews)}명의 에이전트를 인터뷰했습니다."
