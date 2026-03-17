# MiroFish Local Stack Migration + Optimization Design

## Overview

MiroFish의 Zep Cloud 의존성을 완전히 제거하고, **kg-gen + Kuzu DB** 기반 로컬 스택으로 전환한다. 동시에 IMPROVEMENT.md에 명시된 6가지 최적화 전략을 적용하여 시뮬레이션 비용과 시간을 대폭 절감한다.

### Core Constraints

- 모든 LLM 호출 (백엔드, OASIS, kg-gen) → 단일 로컬 llama.cpp 서버 (OpenAI 호환 API)
- Zep Cloud → kg-gen (엔터티/관계 추출) + Kuzu (임베디드 그래프 DB)
- 기존 API 인터페이스와 데이터클래스 유지 (프런트엔드 변경 최소화)

---

## Part 1: Local Stack Migration

### 1.1 Architecture

```
현재:
  API Routes → GraphBuilderService (Zep Cloud)
             → ZepEntityReader (Zep Cloud)
             → OasisProfileGenerator (Zep Cloud + OpenAI API)
             → ZepTools (Zep Cloud)
             → ZepGraphMemoryUpdater (Zep Cloud)

변경 후:
  API Routes → LocalGraphService (kg-gen + Kuzu DB)
             → OasisProfileGenerator (LocalGraphService + 로컬 LLM)
             → LocalGraphTools (Kuzu Cypher 쿼리)
             → LocalGraphMemoryUpdater (Kuzu DB)
```

### 1.2 File Changes

**삭제 (Zep 전용):**
- `services/graph_builder.py`
- `services/zep_entity_reader.py`
- `services/zep_tools.py`
- `services/zep_graph_memory_updater.py`
- `utils/zep_paging.py`

**신규 생성:**
- `services/local_graph_service.py` — kg-gen + Kuzu 통합 서비스
- `services/local_graph_tools.py` — 리포트 에이전트용 Cypher 기반 도구
- `services/local_graph_memory_updater.py` — 시뮬레이션 액션을 Kuzu에 기록

**수정:**
- `config.py` — ZEP_API_KEY 제거, KUZU_DB_DIR / KGGEN_MODEL 추가, `validate()` 수정
- `api/graph.py` — GraphBuilderService → LocalGraphService
- `api/simulation.py` — `ZepEntityReader` → `LocalGraphService` (5곳 참조)
- `api/report.py` — `ZepToolsService` → `LocalGraphToolsService` (2곳 참조)
- `services/oasis_profile_generator.py` — Zep 의존 제거, LocalGraphService 주입
- `services/report_agent.py` — `ZepToolsService` → `LocalGraphToolsService`
- `services/simulation_manager.py` — `ZepEntityReader` import → `LocalGraphService`
- `services/simulation_runner.py` — `ZepGraphMemoryManager` → `LocalGraphMemoryManager`
- `services/simulation_config_generator.py` — `ZepEntityReader` import → `LocalGraphService`
- `services/ontology_generator.py` — Zep ontology import 참조 문자열 제거
- `services/__init__.py` — 모든 Zep 관련 import/export를 새 모듈명으로 교체
- `scripts/run_twitter_simulation.py` — 계층적 에이전트 + 수렴 조기종료
- `scripts/run_reddit_simulation.py` — 동일
- `scripts/run_parallel_simulation.py` — 동일

### 1.3 Kuzu Schema

```cypher
CREATE NODE TABLE Entity (
    uuid STRING PRIMARY KEY,
    graph_id STRING,
    name STRING,
    label STRING,
    summary STRING,
    attributes STRING
)

CREATE REL TABLE RELATES_TO (
    FROM Entity TO Entity,
    relation STRING,
    fact STRING,
    graph_id STRING,
    created_at STRING
)
```

- `graph_id`로 프로젝트별 그래프를 단일 DB 안에서 구분
- `attributes`는 JSON 직렬화 문자열
- Kuzu REL TABLE은 PRIMARY KEY를 지원하지 않음 — 관계 중복 방지는 애플리케이션 레이어에서 처리
- 기존 Zep의 시간 메타데이터(`valid_at`, `invalid_at`, `expired_at`)는 로컬 스택에서 불필요 — 해당 필드는 `get_graph_data()` 반환 시 `None`으로 채움

### 1.4 LocalGraphService Interface

```python
class LocalGraphService:
    """kg-gen + Kuzu 통합 서비스. 기존 5개 Zep 파일을 대체한다."""

    def __init__(self, db_dir: str, llm_base_url: str, llm_api_key: str, llm_model: str):
        """
        Args:
            db_dir: Kuzu DB 디렉터리 경로
            llm_base_url: 로컬 llama.cpp 서버 URL
            llm_api_key: API key (로컬이면 "not-needed")
            llm_model: LiteLLM 포맷 모델명 (예: "openai/local-model")
        """

    # === GraphBuilderService 대체 ===
    def build_graph(self, text, ontology, graph_name, chunk_size=5000,
                    progress_callback=None) -> str:
        """
        텍스트 → kg-gen으로 엔터티/관계 추출 → Kuzu에 저장.
        동기 메서드. 기존 api/graph.py의 build_task() 클로저 내에서 호출됨.
        progress_callback(message: str, progress_ratio: float)으로 진행률 보고.

        흐름:
        1. TextProcessor.split_text()로 청킹 → progress 5-10%
        2. 각 청크에 kg-gen.generate() 호출 → progress 10-60%
           (ontology의 entity_types를 kg-gen context 문자열로 변환하여 전달)
        3. kg-gen.aggregate()로 병합 → progress 60-70%
        4. kg-gen.cluster()로 동일 엔터티 통합 → progress 70-80%
        5. Kuzu INSERT (Entity 노드 + RELATES_TO 엣지) → progress 80-95%
        반환: graph_id

        ontology 변환: 기존 Zep 포맷의 ontology dict를 kg-gen의 context 문자열로 변환.
        예: entity_types=[{name:"student",...}] → "Focus on entities: student, professor, ..."
        """

    def get_graph_info(self, graph_id) -> GraphInfo:
        """Cypher로 노드/엣지 수 조회"""

    def get_graph_data(self, graph_id) -> dict:
        """전체 노드/엣지 데이터를 dict로 반환. 기존 GraphBuilderService.get_graph_data() 동일 형식."""

    def delete_graph(self, graph_id):
        """해당 graph_id의 모든 엔터티/관계 삭제"""

    # === ZepEntityReader 대체 ===
    def get_all_nodes(self, graph_id) -> list:
        """MATCH (n:Entity) WHERE n.graph_id = $id RETURN n"""

    def get_all_edges(self, graph_id) -> list:
        """MATCH ()-[r:RELATES_TO]->() WHERE r.graph_id = $id RETURN r"""

    def filter_defined_entities(self, graph_id, defined_entity_types=None,
                                 enrich_with_edges=True) -> FilteredEntities:
        """라벨 기반 필터링 + 연관 엣지/노드 조회. 기존 FilteredEntities 반환."""

    def get_entity_with_context(self, graph_id, entity_uuid) -> EntityNode:
        """단일 엔터티 + N-hop 관계 컨텍스트 조회. 기존 EntityNode 반환."""

    def get_entities_by_type(self, graph_id, entity_type,
                              enrich_with_edges=True) -> list:
        """특정 타입 엔터티 일괄 조회"""

    # === OasisProfileGenerator용 검색 (Zep 하이브리드 검색 대체) ===
    def search_entity_context(self, graph_id, entity_name) -> dict:
        """
        Cypher로 2-hop 이웃 탐색 (방향 쿼리 2회로 양방향 커버).
        Kuzu는 비방향 패턴을 지원하지 않으므로 UNION ALL 사용:

        MATCH (n:Entity)-[r:RELATES_TO]->(m:Entity)
        WHERE n.graph_id = $gid AND n.name = $name
        RETURN r.fact, m.name, m.summary
        UNION ALL
        MATCH (m:Entity)-[r:RELATES_TO]->(n:Entity)
        WHERE n.graph_id = $gid AND n.name = $name
        RETURN r.fact, m.name, m.summary

        반환: {"facts": [...], "node_summaries": [...], "context": "..."}
        """

    # === Kuzu 커넥션 관리 ===
    def get_connection(self) -> "kuzu.Connection":
        """
        스레드 안전한 커넥션 반환.
        Kuzu Connection은 스레드 안전하지 않으므로 threading.local()로 관리.
        각 스레드가 자신만의 Connection 인스턴스를 사용한다.
        """
```

**핵심**: `EntityNode`, `FilteredEntities`, `GraphInfo` 등 기존 데이터클래스를 그대로 재사용하여 호출자 코드 변경을 최소화한다.

### 1.5 LocalGraphTools Interface

리포트 에이전트(`report_agent.py`)에서 사용하는 3가지 도구를 Cypher 기반으로 재구현한다.

```python
class LocalGraphToolsService:
    """기존 ZepToolsService 완전 대체. report_agent.py가 사용하는 모든 메서드를 포함."""

    def __init__(self, graph_service: LocalGraphService = None, llm_client: LLMClient = None):
        self.graph_service = graph_service or LocalGraphService(...)
        self.llm_client = llm_client or LLMClient(...)

    # === 핵심 분석 도구 (report_agent._execute_tool에서 호출) ===
    def insight_forge(self, query, graph_id, simulation_requirement) -> InsightForgeResult:
        """LLM 서브쿼리 분해 + Cypher CONTAINS 검색"""

    def panorama_search(self, query, graph_id) -> PanoramaResult:
        """전체 노드/엣지 스캔 + 키워드 필터링"""

    def quick_search(self, query, graph_id) -> SearchResult:
        """단순 키워드 검색, LIMIT 20"""

    # === 보조 도구 (report_agent에서 추가 호출) ===
    def interview_agents(self, graph_id, simulation_id, agent_ids, prompt) -> InterviewResult:
        """OASIS IPC를 통한 에이전트 인터뷰. 기존 구현 유지 (IPC 기반, Zep 무관)."""

    def get_graph_statistics(self, graph_id) -> dict:
        """그래프 통계 (노드 수, 엣지 수, 엔터티 타입별 분포)"""

    def get_entity_summary(self, graph_id, entity_name) -> str:
        """특정 엔터티의 요약 정보 반환"""

    def get_entities_by_type(self, graph_id, entity_type) -> list:
        """타입별 엔터티 목록 반환"""

    def get_simulation_context(self, graph_id, simulation_requirement) -> str:
        """시뮬레이션 컨텍스트 요약 문자열 생성"""
```

반환 타입(`InsightForgeResult`, `PanoramaResult`, `SearchResult`, `InterviewResult`, `NodeInfo`, `EdgeInfo`)은 기존 데이터클래스를 `local_graph_tools.py`에 재정의한다 (`.to_text()` 메서드 포함). `EdgeInfo`의 `is_expired`/`is_invalid` 프로퍼티는 항상 `False`를 반환한다 (시간 메타데이터 없음).

### 1.6 LocalGraphMemoryUpdater

기존 `ZepGraphMemoryUpdater`의 큐 + 워커 스레드 패턴을 유지하되, `client.graph.add()` → Kuzu INSERT로 교체.

```python
class LocalGraphMemoryUpdater:
    def __init__(self, graph_id: str, graph_service: LocalGraphService):
        self.graph_service = graph_service
        self.graph_id = graph_id
        # 동일한 Queue + Lock + worker thread 구조

    def _send_batch_activities(self, activities, platform):
        """
        배치 액션을 Kuzu에 엣지로 기록.
        CREATE_POST → agent -[POSTED {fact, created_at}]-> topic_entity
        기타 → 기존 관계에 메타데이터 보강
        """
```

`AgentActivity` 데이터클래스, `LocalGraphMemoryManager` 싱글턴은 기존 구조 유지.

### 1.7 LocalGraphMemoryUpdater Action Mapping

12가지 액션 타입의 Kuzu 기록 매핑:

| 액션 타입 | Kuzu 기록 방식 |
|-----------|---------------|
| CREATE_POST | 새 엣지: agent -[POSTED {fact=content}]-> topic_entity |
| CREATE_COMMENT | 새 엣지: agent -[COMMENTED {fact=content}]-> post_entity |
| LIKE_POST / DISLIKE_POST | 새 엣지: agent -[REACTED {fact=like/dislike}]-> post_entity |
| REPOST / QUOTE_POST | 새 엣지: agent -[SHARED {fact=quote}]-> original_post_entity |
| FOLLOW / MUTE | 새 엣지: agent -[SOCIAL {fact=follow/mute}]-> target_agent |
| LIKE_COMMENT / DISLIKE_COMMENT | 새 엣지: agent -[REACTED {fact=like/dislike}]-> comment_entity |
| SEARCH_POSTS / SEARCH_USER | 기록하지 않음 (그래프 변화 없음) |
| DO_NOTHING | 기록하지 않음 (기존과 동일) |

시뮬레이션 중 생성되는 콘텐츠(게시글, 댓글)는 임시 Entity 노드로 추가하여 관계 그래프를 확장한다.

### 1.8 OasisProfileGenerator 수정

- `from zep_cloud.client import Zep` → 제거
- `from .local_graph_service import LocalGraphService` 추가
- 생성자에서 `zep_api_key` 파라미터 → `graph_service: LocalGraphService` 주입
- `_search_zep_for_entity()` → `self.graph_service.search_entity_context()` 호출
- `_build_entity_context()` 4단계 중 마지막 Zep 검색 → Kuzu 검색으로 교체

### 1.9 Config Changes

```python
class Config:
    # LLM (base_url 기본값을 로컬로 변경)
    LLM_API_KEY = os.environ.get('LLM_API_KEY', 'not-needed')
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'http://localhost:8080/v1')
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', 'local-model')

    # Zep 제거
    # ZEP_API_KEY 삭제

    # Kuzu 추가
    KUZU_DB_DIR = os.environ.get('KUZU_DB_DIR',
        os.path.join(os.path.dirname(__file__), '../data/kuzu_db'))

    # kg-gen
    KGGEN_MODEL = os.environ.get('KGGEN_MODEL', 'openai/local-model')

    # 수렴 조기종료
    CONVERGENCE_THRESHOLD = float(os.environ.get('CONVERGENCE_THRESHOLD', '0.05'))
    CONVERGENCE_CHECK_INTERVAL = int(os.environ.get('CONVERGENCE_CHECK_INTERVAL', '5'))

    @classmethod
    def validate(cls):
        """필수 설정 검증 — ZEP_API_KEY 체크 제거, KUZU_DB_DIR 체크 추가"""
        errors = []
        if not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY가 설정되지 않았습니다.")
        # KUZU_DB_DIR은 기본값이 있으므로 검증 불필요
        return errors
```

### 1.9.1 Thread Safety — Kuzu Connection

Kuzu의 `Connection`은 스레드 안전하지 않다. `LocalGraphService`는 `threading.local()`을 사용하여 스레드별 커넥션을 관리한다:

```python
import threading

class LocalGraphService:
    def __init__(self, db_dir):
        self.db = kuzu.Database(db_dir)  # Database 객체는 스레드 안전
        self._local = threading.local()

    def get_connection(self):
        if not hasattr(self._local, 'conn'):
            self._local.conn = kuzu.Connection(self.db)
        return self._local.conn
```

이 패턴은 `OasisProfileGenerator`의 `ThreadPoolExecutor`(5 workers)와 `LocalGraphMemoryUpdater`의 워커 스레드에서 안전하게 동작한다.

### 1.10 Dependencies

```toml
# 제거
# zep-cloud >= 3.13.0

# 추가
kg-gen = ">=0.1.0"
kuzu = ">=0.11.0"
```

---

## Part 2: Optimization Strategies

### 2.1 Strategy 1 — Persona Compression

페르소나 프롬프트를 2,000자 서술 → 300자 구조화 태그로 변경.

`_build_individual_persona_prompt()`에서:
```
기존: "2. persona: 2000자 이내의 상세 성격/행동 특성"

변경: "2. persona: 300자 이내의 구조화된 캐릭터 태그. 형식:
[성격:MBTI/핵심성향1/핵심성향2] [입장:주제에 대한 태도]
[행동:게시빈도/글스타일/인용습관] [배경:직업/연령대/지역]
[관계:핵심인물과의 관계 요약]"
```

기관/집단 프롬프트도 동일 축소. 입력 토큰 ~1,000 → ~200 절감.

### 2.2 Strategy 2 — Prefix Caching

llama.cpp 서버 레벨 설정. 코드 수정 없음.
권장 실행 옵션: `--cache-type-k f16 --cache-type-v f16`

### 2.3 Strategy 3 — Single Platform Mode

기존 `--twitter-only`, `--reddit-only` CLI 옵션 활용. 코드 수정 없음.

### 2.4 Strategy 4 — Tiered Agents

`simulation_config_generator.py`의 LLM 프롬프트에 tier 배정 지시를 추가:

```
각 에이전트에 tier를 배정하세요:
- tier 1 (15-20%): influence_weight가 높은 핵심 인물. 매 라운드 LLM 결정.
- tier 2 (30%): 중간 영향력. 콘텐츠 생성 시만 LLM 호출.
- tier 3 (50%): 배경 에이전트. 규칙 기반 행동만.
```

`simulation_config.json`의 `agent_configs`에 `tier` 필드 추가.

시뮬레이션 스크립트에서 tier 기반 액션 분기:
- Tier 1: `LLMAction()`
- Tier 2: `CREATE_POST`/`CREATE_COMMENT` → `LLMAction()`, 나머지 → `rule_based_action()`
- Tier 3: 전부 `rule_based_action()`

### 2.5 Strategy 5 — Action Routing (HybridAction)

Tier 2/3 에이전트용 규칙 기반 액션 결정:

```python
def rule_based_action(agent_config, feed_items):
    if not feed_items:
        return ManualAction(ActionType.DO_NOTHING)
    relevance = compute_topic_relevance(agent_config, feed_items)
    if relevance > 0.7:
        roll = random.random()
        if roll < 0.4: return ManualAction(ActionType.LIKE_POST, ...)
        elif roll < 0.6: return ManualAction(ActionType.REPOST, ...)
        else: return ManualAction(ActionType.DO_NOTHING)
    else:
        return ManualAction(ActionType.DO_NOTHING)
```

`compute_topic_relevance()`는 에이전트의 `interested_topics`와 피드 콘텐츠의 키워드 매칭으로 구현.

### 2.6 Strategy 6 — Convergence Early Stopping

시뮬레이션 라운드 루프에 수렴 체크 삽입:

```python
if round_num % CONVERGENCE_CHECK_INTERVAL == 0 and round_num > 0:
    recent_dist = compute_action_distribution(actions_log, last_n_rounds=5)
    kl_div = kl_divergence(recent_dist, previous_checkpoint_dist)
    if kl_div < CONVERGENCE_THRESHOLD:
        logger.info(f"Round {round_num}: convergence detected, stopping early")
        break
    previous_checkpoint_dist = recent_dist
```

`run_twitter_simulation.py`와 `run_reddit_simulation.py` 양쪽에 적용.

---

## Implementation Priority

1. **Config + Dependencies** — Zep 제거, Kuzu/kg-gen 추가
2. **LocalGraphService** — 핵심 서비스 구현
3. **API 라우트 수정** — graph.py, simulation.py
4. **OasisProfileGenerator 수정** — Zep 제거 + 페르소나 압축 (전략 1)
5. **LocalGraphTools** — 리포트 에이전트용 도구
6. **LocalGraphMemoryUpdater** — 시뮬레이션 메모리 업데이터
7. **Tiered Agents + Action Routing** — 시뮬레이션 스크립트 (전략 4, 5)
8. **Convergence Early Stopping** — 시뮬레이션 스크립트 (전략 6)
9. **Cleanup** — 삭제 대상 Zep 파일 제거, imports 정리
