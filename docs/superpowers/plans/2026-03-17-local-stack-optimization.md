# Local Stack Migration + Optimization Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Zep Cloud with kg-gen + Kuzu DB for a fully local stack, then apply 6 optimization strategies to reduce simulation cost by 90%+.

**Architecture:** A single `LocalGraphService` class wraps kg-gen (knowledge graph extraction) and Kuzu (embedded graph DB) to replace 5 Zep-dependent files. `LocalGraphService` is a **singleton** — created once at Flask app startup and shared across all requests (Kuzu `Database` uses file-level locking, so only one instance should exist per process). All LLM calls route to a local llama.cpp server via OpenAI-compatible API. Existing dataclasses (`EntityNode`, `FilteredEntities`, `GraphInfo`) are preserved to minimize caller changes.

**Important notes:**
- Kuzu schema DDL must use `IF NOT EXISTS` to be idempotent: `CREATE NODE TABLE IF NOT EXISTS Entity ...`
- All simulation action edges use the single `RELATES_TO` table with the `relation` column storing the action type (e.g., `relation='POSTED'`, `relation='REACTED'`). No new REL TABLEs are needed.
- kg-gen's `generate()` returns an object with `.entities` (set of strings), `.edges` (set of strings), `.relations` (set of (str, str, str) tuples). Verify against kg-gen docs before implementing.

**Tech Stack:** Python 3.11+, kg-gen, Kuzu, Flask, CAMEL-OASIS, OpenAI SDK (pointing to local llama.cpp)

**Spec:** `docs/superpowers/specs/2026-03-17-local-stack-optimization-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `backend/app/services/local_graph_service.py` | kg-gen + Kuzu integration. Graph building, entity querying, context search. Replaces `graph_builder.py` + `zep_entity_reader.py`. |
| `backend/app/services/local_graph_tools.py` | Report agent tools (InsightForge, PanoramaSearch, QuickSearch, interview, statistics). Replaces `zep_tools.py`. |
| `backend/app/services/local_graph_memory_updater.py` | Records simulation actions to Kuzu. Replaces `zep_graph_memory_updater.py`. |
| `backend/app/utils/action_routing.py` | Shared `rule_based_action()` and `compute_topic_relevance()` for Tier 2/3 agents. Used by all 3 simulation scripts. |
| `backend/tests/test_local_graph_service.py` | Tests for LocalGraphService |
| `backend/tests/test_local_graph_tools.py` | Tests for LocalGraphToolsService |
| `backend/tests/test_local_graph_memory_updater.py` | Tests for LocalGraphMemoryUpdater |
| `backend/tests/test_persona_compression.py` | Tests for compressed persona prompt |
| `backend/tests/test_tiered_agents.py` | Tests for tiered agent + convergence logic |
| `backend/tests/__init__.py` | Test package init |
| `backend/tests/conftest.py` | Shared fixtures (temp Kuzu DB, mock LLM) |

### Modified Files
| File | Change |
|------|--------|
| `backend/pyproject.toml` | Remove `zep-cloud`, add `kg-gen`, `kuzu` |
| `backend/app/config.py` | Remove `ZEP_API_KEY`, add `KUZU_DB_DIR`, `KGGEN_MODEL`, convergence settings |
| `backend/app/services/__init__.py` | Replace all Zep imports with local equivalents |
| `backend/app/api/graph.py` | `GraphBuilderService` → `LocalGraphService` |
| `backend/app/api/simulation.py` | `ZepEntityReader` → `LocalGraphService` |
| `backend/app/api/report.py` | `ZepToolsService` → `LocalGraphToolsService` |
| `backend/app/services/oasis_profile_generator.py` | Remove Zep, inject `LocalGraphService`, compress persona prompts |
| `backend/app/services/report_agent.py` | `ZepToolsService` → `LocalGraphToolsService` |
| `backend/app/services/simulation_manager.py` | `ZepEntityReader` → `LocalGraphService` |
| `backend/app/services/simulation_runner.py` | `ZepGraphMemoryManager` → `LocalGraphMemoryManager` |
| `backend/app/services/simulation_config_generator.py` | `ZepEntityReader` import → `LocalGraphService`, add tier prompt |
| `backend/app/services/ontology_generator.py` | Remove Zep ontology import string reference |
| `backend/scripts/run_twitter_simulation.py` | Tiered agents, rule-based action, convergence early stop |
| `backend/scripts/run_reddit_simulation.py` | Same changes as twitter |
| `backend/scripts/run_parallel_simulation.py` | Same changes |

### Deleted Files (Task 9)
| File | Reason |
|------|--------|
| `backend/app/services/graph_builder.py` | Replaced by `local_graph_service.py` |
| `backend/app/services/zep_entity_reader.py` | Replaced by `local_graph_service.py` |
| `backend/app/services/zep_tools.py` | Replaced by `local_graph_tools.py` |
| `backend/app/services/zep_graph_memory_updater.py` | Replaced by `local_graph_memory_updater.py` |
| `backend/app/utils/zep_paging.py` | No longer needed (Kuzu is embedded) |

---

## Task 1: Dependencies + Config

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/app/config.py`
- Modify: `backend/.env.example` (if exists)
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`

- [ ] **Step 1: Update pyproject.toml — remove zep-cloud, add kg-gen + kuzu**

In `backend/pyproject.toml`, replace:
```toml
    # Zep Cloud
    "zep-cloud==3.13.0",
```
With:
```toml
    # Knowledge Graph (local)
    "kg-gen>=0.1.0",
    "kuzu>=0.11.0",
```

- [ ] **Step 2: Update config.py — remove ZEP, add Kuzu/kg-gen settings**

In `backend/app/config.py`:

Remove:
```python
    # Zep 설정
    ZEP_API_KEY = os.environ.get('ZEP_API_KEY')
```

Add after LLM settings:
```python
    # Kuzu 그래프 DB (로컬)
    KUZU_DB_DIR = os.environ.get('KUZU_DB_DIR',
        os.path.join(os.path.dirname(__file__), '../data/kuzu_db'))

    # kg-gen (LiteLLM 포맷)
    KGGEN_MODEL = os.environ.get('KGGEN_MODEL', 'openai/local-model')

    # 수렴 조기종료
    CONVERGENCE_THRESHOLD = float(os.environ.get('CONVERGENCE_THRESHOLD', '0.05'))
    CONVERGENCE_CHECK_INTERVAL = int(os.environ.get('CONVERGENCE_CHECK_INTERVAL', '5'))
```

Change LLM defaults:
```python
    LLM_API_KEY = os.environ.get('LLM_API_KEY', 'not-needed')
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'http://localhost:8080/v1')
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', 'local-model')
```

Update `validate()`:
```python
    @classmethod
    def validate(cls):
        errors = []
        if not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY가 설정되지 않았습니다.")
        return errors
```

- [ ] **Step 3: Create test infrastructure**

Create `backend/tests/__init__.py` (empty file).

Create `backend/tests/conftest.py`:
```python
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
    conn.close()
    shutil.rmtree(tmp_dir, ignore_errors=True)
```

- [ ] **Step 4: Add LocalGraphService singleton helper to config.py**

Add at the bottom of `backend/app/config.py`:
```python
# Singleton LocalGraphService instance (created on first access)
_graph_service_instance = None

def get_graph_service():
    """Return the app-wide LocalGraphService singleton."""
    global _graph_service_instance
    if _graph_service_instance is None:
        from .services.local_graph_service import LocalGraphService
        _graph_service_instance = LocalGraphService(
            db_dir=Config.KUZU_DB_DIR,
            llm_base_url=Config.LLM_BASE_URL,
            llm_api_key=Config.LLM_API_KEY,
            llm_model=Config.KGGEN_MODEL
        )
    return _graph_service_instance
```

All routes and services that need `LocalGraphService` will call `get_graph_service()` instead of creating their own instance.

- [ ] **Step 5: Install new dependencies**

Run: `cd /Users/reasoner/IdeaOrganizer/mirofish-predict/backend && uv sync`
Expected: Successful installation of kg-gen and kuzu.

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/app/config.py backend/tests/__init__.py backend/tests/conftest.py
git commit -m "feat: replace zep-cloud deps with kg-gen + kuzu, update config"
```

---

## Task 2: LocalGraphService — Core (Schema + Entity Read)

**Files:**
- Create: `backend/app/services/local_graph_service.py`
- Create: `backend/tests/test_local_graph_service.py`

- [ ] **Step 1: Write failing tests for schema init + entity CRUD**

Create `backend/tests/test_local_graph_service.py`:
```python
import json
import pytest
from app.services.local_graph_service import LocalGraphService, GraphInfo, EntityNode, FilteredEntities


class TestLocalGraphServiceSchema:
    def test_init_creates_schema(self, tmp_kuzu_db):
        tmp_dir, _, _ = tmp_kuzu_db
        # Service should init without error on already-created schema
        svc = LocalGraphService(db_dir=tmp_dir, llm_base_url="http://localhost:8080/v1",
                                llm_api_key="test", llm_model="openai/test")
        assert svc.db is not None

    def test_get_all_nodes_empty(self, tmp_kuzu_db):
        tmp_dir, _, _ = tmp_kuzu_db
        svc = LocalGraphService(db_dir=tmp_dir, llm_base_url="http://localhost:8080/v1",
                                llm_api_key="test", llm_model="openai/test")
        nodes = svc.get_all_nodes("nonexistent_graph")
        assert nodes == []

    def test_insert_and_query_nodes(self, tmp_kuzu_db):
        tmp_dir, db, conn = tmp_kuzu_db
        # Insert test data directly
        conn.execute("""
            CREATE (e:Entity {uuid: 'u1', graph_id: 'g1', name: 'Alice',
                              label: 'student', summary: 'A student', attributes: '{}'})
        """)
        conn.execute("""
            CREATE (e:Entity {uuid: 'u2', graph_id: 'g1', name: 'Bob',
                              label: 'professor', summary: 'A professor', attributes: '{}'})
        """)
        svc = LocalGraphService(db_dir=tmp_dir, llm_base_url="http://localhost:8080/v1",
                                llm_api_key="test", llm_model="openai/test")
        nodes = svc.get_all_nodes("g1")
        assert len(nodes) == 2
        names = {n["name"] for n in nodes}
        assert names == {"Alice", "Bob"}

    def test_filter_defined_entities(self, tmp_kuzu_db):
        tmp_dir, db, conn = tmp_kuzu_db
        conn.execute("""
            CREATE (e:Entity {uuid: 'u1', graph_id: 'g1', name: 'Alice',
                              label: 'student', summary: 'A student', attributes: '{}'})
        """)
        conn.execute("""
            CREATE (e:Entity {uuid: 'u2', graph_id: 'g1', name: 'MIT',
                              label: 'university', summary: 'A university', attributes: '{}'})
        """)
        svc = LocalGraphService(db_dir=tmp_dir, llm_base_url="http://localhost:8080/v1",
                                llm_api_key="test", llm_model="openai/test")
        result = svc.filter_defined_entities("g1", defined_entity_types=["student"])
        assert result.filtered_count == 1
        assert result.entities[0].name == "Alice"

    def test_get_graph_info(self, tmp_kuzu_db):
        tmp_dir, db, conn = tmp_kuzu_db
        conn.execute("""
            CREATE (e:Entity {uuid: 'u1', graph_id: 'g1', name: 'Alice',
                              label: 'student', summary: 'test', attributes: '{}'})
        """)
        svc = LocalGraphService(db_dir=tmp_dir, llm_base_url="http://localhost:8080/v1",
                                llm_api_key="test", llm_model="openai/test")
        info = svc.get_graph_info("g1")
        assert info.node_count == 1
        assert info.edge_count == 0
        assert "student" in info.entity_types

    def test_get_graph_data_format(self, tmp_kuzu_db):
        tmp_dir, db, conn = tmp_kuzu_db
        conn.execute("""
            CREATE (e:Entity {uuid: 'u1', graph_id: 'g1', name: 'Alice',
                              label: 'student', summary: 'test', attributes: '{}'})
        """)
        svc = LocalGraphService(db_dir=tmp_dir, llm_base_url="http://localhost:8080/v1",
                                llm_api_key="test", llm_model="openai/test")
        data = svc.get_graph_data("g1")
        assert "nodes" in data
        assert "edges" in data
        assert "node_count" in data
        node = data["nodes"][0]
        # Verify temporal fields are None (Zep compat)
        assert "created_at" in node

    def test_delete_graph(self, tmp_kuzu_db):
        tmp_dir, db, conn = tmp_kuzu_db
        conn.execute("""
            CREATE (e:Entity {uuid: 'u1', graph_id: 'g1', name: 'Alice',
                              label: 'student', summary: 'test', attributes: '{}'})
        """)
        svc = LocalGraphService(db_dir=tmp_dir, llm_base_url="http://localhost:8080/v1",
                                llm_api_key="test", llm_model="openai/test")
        svc.delete_graph("g1")
        assert svc.get_all_nodes("g1") == []

    def test_search_entity_context(self, tmp_kuzu_db):
        tmp_dir, db, conn = tmp_kuzu_db
        conn.execute("""
            CREATE (a:Entity {uuid: 'u1', graph_id: 'g1', name: 'Alice',
                              label: 'student', summary: 'A student', attributes: '{}'})
        """)
        conn.execute("""
            CREATE (b:Entity {uuid: 'u2', graph_id: 'g1', name: 'Bob',
                              label: 'professor', summary: 'A professor', attributes: '{}'})
        """)
        conn.execute("""
            MATCH (a:Entity {uuid: 'u1'}), (b:Entity {uuid: 'u2'})
            CREATE (a)-[:RELATES_TO {relation: 'studies_under', fact: 'Alice studies under Bob',
                                     graph_id: 'g1', created_at: '2026-01-01'}]->(b)
        """)
        svc = LocalGraphService(db_dir=tmp_dir, llm_base_url="http://localhost:8080/v1",
                                llm_api_key="test", llm_model="openai/test")
        ctx = svc.search_entity_context("g1", "Alice")
        assert len(ctx["facts"]) > 0
        assert "Alice studies under Bob" in ctx["facts"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/reasoner/IdeaOrganizer/mirofish-predict/backend && uv run python -m pytest tests/test_local_graph_service.py -v`
Expected: ImportError — `local_graph_service` module not found.

- [ ] **Step 3: Implement LocalGraphService (read/query methods)**

Create `backend/app/services/local_graph_service.py` with:
- `__init__` that opens Kuzu DB, creates schema if not exists, inits kg-gen
- `get_connection()` with `threading.local()` for thread safety
- `get_all_nodes(graph_id)` — Cypher SELECT
- `get_all_edges(graph_id)` — Cypher SELECT
- `get_graph_info(graph_id)` → `GraphInfo`
- `get_graph_data(graph_id)` → dict with Zep-compatible format (temporal fields = None)
- `filter_defined_entities(graph_id, types, enrich)` → `FilteredEntities`
- `get_entity_with_context(graph_id, uuid)` → `EntityNode`
- `get_entities_by_type(graph_id, type)` → list
- `search_entity_context(graph_id, name)` → dict with facts/node_summaries/context
- `delete_graph(graph_id)` — Cypher DELETE
- Preserve `EntityNode`, `FilteredEntities`, `GraphInfo` dataclass interfaces from `zep_entity_reader.py` and `graph_builder.py`

Key implementation notes:
- All Cypher queries use directed patterns with UNION ALL for bidirectional traversal
- `attributes` field: `json.dumps()` on write, `json.loads()` on read
- `get_graph_data()` returns `valid_at`, `invalid_at`, `expired_at` as `None`

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/reasoner/IdeaOrganizer/mirofish-predict/backend && uv run python -m pytest tests/test_local_graph_service.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/local_graph_service.py backend/tests/test_local_graph_service.py
git commit -m "feat: add LocalGraphService with Kuzu-backed entity read/query"
```

---

## Task 3: LocalGraphService — Graph Building (kg-gen integration)

**Files:**
- Modify: `backend/app/services/local_graph_service.py`
- Modify: `backend/tests/test_local_graph_service.py`

- [ ] **Step 1: Write failing test for build_graph**

Add to `backend/tests/test_local_graph_service.py`:
```python
from unittest.mock import patch, MagicMock


class TestLocalGraphServiceBuild:
    def test_build_graph_from_text(self, tmp_kuzu_db):
        tmp_dir, _, _ = tmp_kuzu_db
        svc = LocalGraphService(db_dir=tmp_dir, llm_base_url="http://localhost:8080/v1",
                                llm_api_key="test", llm_model="openai/test")

        # Mock kg-gen to avoid real LLM calls
        mock_graph = MagicMock()
        mock_graph.entities = {"Alice", "Bob"}
        mock_graph.edges = {"studies_under"}
        mock_graph.relations = {("Alice", "studies_under", "Bob")}

        with patch.object(svc.kg, 'generate', return_value=mock_graph), \
             patch.object(svc.kg, 'aggregate', return_value=mock_graph), \
             patch.object(svc.kg, 'cluster', return_value=mock_graph):

            ontology = {"entity_types": [{"name": "student"}, {"name": "professor"}]}
            graph_id = svc.build_graph(
                text="Alice is a student who studies under professor Bob.",
                ontology=ontology,
                graph_name="Test Graph"
            )

        assert graph_id is not None
        nodes = svc.get_all_nodes(graph_id)
        assert len(nodes) == 2
        info = svc.get_graph_info(graph_id)
        assert info.edge_count == 1

    def test_build_graph_progress_callback(self, tmp_kuzu_db):
        tmp_dir, _, _ = tmp_kuzu_db
        svc = LocalGraphService(db_dir=tmp_dir, llm_base_url="http://localhost:8080/v1",
                                llm_api_key="test", llm_model="openai/test")

        mock_graph = MagicMock()
        mock_graph.entities = {"Alice"}
        mock_graph.edges = set()
        mock_graph.relations = set()

        progress_calls = []
        def track_progress(msg, ratio):
            progress_calls.append((msg, ratio))

        with patch.object(svc.kg, 'generate', return_value=mock_graph), \
             patch.object(svc.kg, 'aggregate', return_value=mock_graph), \
             patch.object(svc.kg, 'cluster', return_value=mock_graph):

            svc.build_graph(text="Alice.", ontology={}, graph_name="Test",
                           progress_callback=track_progress)

        assert len(progress_calls) > 0
        # Last progress should be near 95%
        assert progress_calls[-1][1] >= 0.8
```

- [ ] **Step 2: Run tests to verify the new tests fail**

Run: `cd /Users/reasoner/IdeaOrganizer/mirofish-predict/backend && uv run python -m pytest tests/test_local_graph_service.py::TestLocalGraphServiceBuild -v`
Expected: FAIL — `build_graph` method not implemented.

- [ ] **Step 3: Implement build_graph method**

Add to `LocalGraphService`:
- `build_graph(text, ontology, graph_name, chunk_size, progress_callback)`:
  1. Generate `graph_id = f"mirofish_{uuid.uuid4().hex[:16]}"`
  2. Chunk text with `TextProcessor.split_text()`
  3. Build ontology context string from `ontology["entity_types"]`
  4. For each chunk: `self.kg.generate(input_data=chunk, context=context_str, chunk_size=chunk_size)`
  5. `self.kg.aggregate(chunk_graphs)`
  6. `self.kg.cluster(aggregated, context=context_str)`
  7. For each entity in `clustered.entities`: INSERT Entity node with generated UUID
  8. For each relation `(src, rel, tgt)` in `clustered.relations`: INSERT RELATES_TO edge
  9. Report progress via callback at each stage

- `_ontology_to_context(ontology)`: Converts ontology dict to context string for kg-gen.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/reasoner/IdeaOrganizer/mirofish-predict/backend && uv run python -m pytest tests/test_local_graph_service.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/local_graph_service.py backend/tests/test_local_graph_service.py
git commit -m "feat: add build_graph with kg-gen integration"
```

---

## Task 4: Config + API Route Migration (graph.py)

**Files:**
- Modify: `backend/app/api/graph.py`

- [ ] **Step 1: Update graph.py imports and service usage**

In `backend/app/api/graph.py`:

Replace:
```python
from ..services.graph_builder import GraphBuilderService
```
With:
```python
from ..config import get_graph_service
```

In `build_graph()` route's `build_task()` closure, replace:
```python
builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)
```
With:
```python
builder = get_graph_service()
```

Replace the entire build_task flow (create_graph → set_ontology → add_text_batches → wait_for_episodes → get_graph_data) with a single `builder.build_graph()` call:
```python
graph_id = builder.build_graph(
    text=text,
    ontology=ontology,
    graph_name=graph_name,
    chunk_size=chunk_size,
    progress_callback=lambda msg, ratio: task_manager.update_task(
        task_id, message=msg, progress=int(ratio * 95)
    )
)
```

Remove all `Config.ZEP_API_KEY` checks in graph.py (build, get_graph_data, delete_graph endpoints).

In `get_graph_data()` and `delete_graph()` routes, replace `GraphBuilderService(api_key=Config.ZEP_API_KEY)` with `get_graph_service()`.

- [ ] **Step 2: Verify no remaining Zep references in graph.py**

Run: `grep -n "zep\|Zep\|ZEP" backend/app/api/graph.py`
Expected: No matches.

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/graph.py
git commit -m "feat: migrate graph.py API routes from Zep to LocalGraphService"
```

---

## Task 5: API Route Migration (simulation.py + report.py)

**Files:**
- Modify: `backend/app/api/simulation.py`
- Modify: `backend/app/api/report.py`

- [ ] **Step 1: Update simulation.py**

Replace import:
```python
from ..services.zep_entity_reader import ZepEntityReader
```
With:
```python
from ..config import get_graph_service
```

Replace all 5 occurrences of:
```python
reader = ZepEntityReader()
```
With:
```python
reader = get_graph_service()
```

The method signatures (`get_all_nodes`, `filter_defined_entities`, `get_entities_by_type`) are the same on `LocalGraphService`, so no further changes needed.

**Also remove all `Config.ZEP_API_KEY` guard clauses** in simulation.py. Find and remove blocks like:
```python
if not Config.ZEP_API_KEY:
    return jsonify({"success": False, "error": "ZEP_API_KEY가 설정되지 않았습니다"}), 500
```
These checks appear in approximately 3 route handlers and will block all simulation endpoints since `ZEP_API_KEY` no longer exists.

- [ ] **Step 2: Update report.py**

Replace both occurrences of:
```python
from ..services.zep_tools import ZepToolsService
...
tools = ZepToolsService()
```
With:
```python
from ..services.local_graph_tools import LocalGraphToolsService
...
tools = LocalGraphToolsService()
```

- [ ] **Step 3: Verify no remaining Zep references**

Run: `grep -n "zep\|Zep\|ZEP" backend/app/api/simulation.py backend/app/api/report.py`
Expected: No matches.

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/simulation.py backend/app/api/report.py
git commit -m "feat: migrate simulation.py and report.py from Zep to local services"
```

---

## Task 6: OasisProfileGenerator Migration + Persona Compression

**Files:**
- Modify: `backend/app/services/oasis_profile_generator.py`
- Create: `backend/tests/test_persona_compression.py`

- [ ] **Step 1: Write test for compressed persona format**

Create `backend/tests/test_persona_compression.py`:
```python
from app.services.oasis_profile_generator import OasisProfileGenerator


class TestPersonaCompression:
    def test_individual_prompt_requests_300_chars(self):
        gen = OasisProfileGenerator.__new__(OasisProfileGenerator)
        prompt = gen._build_individual_persona_prompt(
            entity_name="Alice",
            entity_type="student",
            entity_summary="A diligent student",
            entity_attributes={},
            context=""
        )
        assert "300자" in prompt or "300" in prompt
        assert "[성격:" in prompt or "structured" in prompt.lower()
        # Must NOT request 2000 chars
        assert "2000" not in prompt

    def test_group_prompt_requests_300_chars(self):
        gen = OasisProfileGenerator.__new__(OasisProfileGenerator)
        prompt = gen._build_group_persona_prompt(
            entity_name="MIT",
            entity_type="university",
            entity_summary="A university",
            entity_attributes={},
            context=""
        )
        assert "300자" in prompt or "300" in prompt
        assert "2000" not in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/reasoner/IdeaOrganizer/mirofish-predict/backend && uv run python -m pytest tests/test_persona_compression.py -v`
Expected: FAIL — prompts still contain "2000".

- [ ] **Step 3: Update OasisProfileGenerator**

In `backend/app/services/oasis_profile_generator.py`:

Remove imports:
```python
from zep_cloud.client import Zep
from .zep_entity_reader import EntityNode, ZepEntityReader
```

Add imports:
```python
from .local_graph_service import LocalGraphService, EntityNode
```

Change constructor — replace `zep_api_key` param with `graph_service`:
```python
def __init__(self, api_key=None, base_url=None, model_name=None,
             graph_service=None, graph_id=None):
    ...
    self.graph_service = graph_service
    self.graph_id = graph_id
```

Remove `self.zep_client` and `self.zep_api_key` references.

Replace `_search_zep_for_entity()` body with:
```python
def _search_zep_for_entity(self, entity):
    if not self.graph_service or not self.graph_id:
        return {"facts": [], "node_summaries": [], "context": ""}
    return self.graph_service.search_entity_context(self.graph_id, entity.name)
```

Update `_build_individual_persona_prompt()` — replace persona instruction:
```python
"""2. persona: 300자 이내의 구조화된 캐릭터 태그. 반드시 아래 형식을 따르세요:
[성격:MBTI/핵심성향1/핵심성향2] [입장:주제에 대한 태도]
[행동:게시빈도/글스타일/인용습관] [배경:직업/연령대/지역]
[관계:핵심인물과의 관계 요약]

예시: [성격:INTJ/비판적/분석적] [입장:기술낙관론] [행동:저빈도/긴글/데이터인용] [배경:금융분석가/40대/서울] [관계:X와 협력, Y와 대립]"""
```

Same change for `_build_group_persona_prompt()`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/reasoner/IdeaOrganizer/mirofish-predict/backend && uv run python -m pytest tests/test_persona_compression.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/oasis_profile_generator.py backend/tests/test_persona_compression.py
git commit -m "feat: migrate profile generator to LocalGraphService + compress persona to 300 chars"
```

---

## Task 7: LocalGraphToolsService

**Files:**
- Create: `backend/app/services/local_graph_tools.py`
- Create: `backend/tests/test_local_graph_tools.py`
- Modify: `backend/app/services/report_agent.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_local_graph_tools.py`:
```python
import pytest
from app.services.local_graph_service import LocalGraphService
from app.services.local_graph_tools import LocalGraphToolsService, SearchResult


class TestLocalGraphTools:
    def test_quick_search_finds_matching_facts(self, tmp_kuzu_db):
        tmp_dir, db, conn = tmp_kuzu_db
        conn.execute("""
            CREATE (a:Entity {uuid: 'u1', graph_id: 'g1', name: 'Alice',
                              label: 'student', summary: 'A student', attributes: '{}'})
        """)
        conn.execute("""
            CREATE (b:Entity {uuid: 'u2', graph_id: 'g1', name: 'Bob',
                              label: 'professor', summary: 'A prof', attributes: '{}'})
        """)
        conn.execute("""
            MATCH (a:Entity {uuid: 'u1'}), (b:Entity {uuid: 'u2'})
            CREATE (a)-[:RELATES_TO {relation: 'studies_under',
                fact: 'Alice studies under Bob at MIT', graph_id: 'g1',
                created_at: '2026-01-01'}]->(b)
        """)
        graph_svc = LocalGraphService(db_dir=tmp_dir, llm_base_url="http://localhost:8080/v1",
                                       llm_api_key="test", llm_model="openai/test")
        tools = LocalGraphToolsService(graph_service=graph_svc)
        result = tools.quick_search("Alice", "g1")
        assert isinstance(result, SearchResult)
        assert result.total_count > 0
        assert any("Alice" in f for f in result.facts)

    def test_get_graph_statistics(self, tmp_kuzu_db):
        tmp_dir, db, conn = tmp_kuzu_db
        conn.execute("""
            CREATE (a:Entity {uuid: 'u1', graph_id: 'g1', name: 'Alice',
                              label: 'student', summary: 'test', attributes: '{}'})
        """)
        graph_svc = LocalGraphService(db_dir=tmp_dir, llm_base_url="http://localhost:8080/v1",
                                       llm_api_key="test", llm_model="openai/test")
        tools = LocalGraphToolsService(graph_service=graph_svc)
        stats = tools.get_graph_statistics("g1")
        assert stats["node_count"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/reasoner/IdeaOrganizer/mirofish-predict/backend && uv run python -m pytest tests/test_local_graph_tools.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement LocalGraphToolsService**

Create `backend/app/services/local_graph_tools.py` with:
- All dataclasses: `SearchResult`, `NodeInfo`, `EdgeInfo`, `InsightForgeResult`, `PanoramaResult`, `InterviewResult` (copy from `zep_tools.py`, remove Zep-specific temporal logic, `is_expired`/`is_invalid` always return `False`)
- `LocalGraphToolsService` class with all 8 methods from spec section 1.5
- `quick_search()`: Cypher CONTAINS on fact/name fields
- `panorama_search()`: Full scan with keyword filter
- `insight_forge()`: LLM sub-query decomposition + Cypher searches
- `interview_agents()`: Copy IPC-based implementation from existing `zep_tools.py` (this part is Zep-independent)
- `get_graph_statistics()`: COUNT queries on Kuzu
- `get_entity_summary()`, `get_entities_by_type()`, `get_simulation_context()`: Delegate to `self.graph_service`

- [ ] **Step 4: Update report_agent.py imports and attribute names**

In `backend/app/services/report_agent.py`:

Replace import block:
```python
from .zep_tools import (
    ZepToolsService,
    SearchResult,
    InsightForgeResult,
    PanoramaResult,
    InterviewResult
)
```
With:
```python
from .local_graph_tools import (
    LocalGraphToolsService,
    SearchResult,
    InsightForgeResult,
    PanoramaResult,
    InterviewResult
)
```

Then do a full find-and-replace across the file:
- `ZepToolsService` → `LocalGraphToolsService` (class name in type hints, constructor)
- `self.zep_tools` → `self.graph_tools` (attribute name, ~12 occurrences)
- `zep_tools` constructor parameter → `graph_tools`
- Logger name `'mirofish.zep_tools'` → `'mirofish.local_graph_tools'` (in ReportLogger class)

- [ ] **Step 5: Run tests**

Run: `cd /Users/reasoner/IdeaOrganizer/mirofish-predict/backend && uv run python -m pytest tests/test_local_graph_tools.py -v`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/local_graph_tools.py backend/tests/test_local_graph_tools.py backend/app/services/report_agent.py
git commit -m "feat: add LocalGraphToolsService, migrate report_agent.py"
```

---

## Task 8: LocalGraphMemoryUpdater

**Files:**
- Create: `backend/app/services/local_graph_memory_updater.py`
- Create: `backend/tests/test_local_graph_memory_updater.py`
- Modify: `backend/app/services/simulation_runner.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_local_graph_memory_updater.py`:
```python
import time
import pytest
from app.services.local_graph_service import LocalGraphService
from app.services.local_graph_memory_updater import (
    LocalGraphMemoryUpdater, LocalGraphMemoryManager, AgentActivity
)


class TestLocalGraphMemoryUpdater:
    def test_add_create_post_activity(self, tmp_kuzu_db):
        tmp_dir, db, conn = tmp_kuzu_db
        # Insert an agent entity
        conn.execute("""
            CREATE (e:Entity {uuid: 'agent_0', graph_id: 'g1', name: 'Alice',
                              label: 'student', summary: 'A student', attributes: '{}'})
        """)
        graph_svc = LocalGraphService(db_dir=tmp_dir, llm_base_url="http://localhost:8080/v1",
                                       llm_api_key="test", llm_model="openai/test")
        updater = LocalGraphMemoryUpdater("g1", graph_svc)
        updater.start()
        activity = AgentActivity(
            platform="twitter", agent_id=0, agent_name="Alice",
            action_type="CREATE_POST",
            action_args={"content": "Hello world!"},
            round_num=1, timestamp="2026-01-01T00:00:00"
        )
        updater.add_activity(activity)
        time.sleep(2)  # Wait for worker to process
        updater.stop()
        stats = updater.get_stats()
        assert stats["total_activities"] >= 1

    def test_do_nothing_is_skipped(self, tmp_kuzu_db):
        tmp_dir, _, _ = tmp_kuzu_db
        graph_svc = LocalGraphService(db_dir=tmp_dir, llm_base_url="http://localhost:8080/v1",
                                       llm_api_key="test", llm_model="openai/test")
        updater = LocalGraphMemoryUpdater("g1", graph_svc)
        activity = AgentActivity(
            platform="twitter", agent_id=0, agent_name="Alice",
            action_type="DO_NOTHING", action_args={},
            round_num=1, timestamp="2026-01-01T00:00:00"
        )
        updater.add_activity(activity)
        assert updater.get_stats()["skipped_count"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/reasoner/IdeaOrganizer/mirofish-predict/backend && uv run python -m pytest tests/test_local_graph_memory_updater.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement LocalGraphMemoryUpdater**

Create `backend/app/services/local_graph_memory_updater.py`:
- Copy `AgentActivity` dataclass from `zep_graph_memory_updater.py` (all 12 action description methods)
- `LocalGraphMemoryUpdater` — same Queue + Lock + worker thread structure as `ZepGraphMemoryUpdater`
- Replace `_send_batch_activities()` Zep call with Kuzu INSERT per the action mapping table in spec 1.7
- `LocalGraphMemoryManager` — same singleton pattern, rename from `ZepGraphMemoryManager`

- [ ] **Step 4: Update simulation_runner.py**

Replace:
```python
from .zep_graph_memory_updater import ZepGraphMemoryManager
```
With:
```python
from .local_graph_memory_updater import LocalGraphMemoryManager
```

Replace all `ZepGraphMemoryManager` references with `LocalGraphMemoryManager`.

- [ ] **Step 5: Run tests**

Run: `cd /Users/reasoner/IdeaOrganizer/mirofish-predict/backend && uv run python -m pytest tests/test_local_graph_memory_updater.py -v`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/local_graph_memory_updater.py backend/tests/test_local_graph_memory_updater.py backend/app/services/simulation_runner.py
git commit -m "feat: add LocalGraphMemoryUpdater, migrate simulation_runner.py"
```

---

## Task 9: Remaining Import Migrations + Zep Cleanup

**Files:**
- Modify: `backend/app/services/__init__.py`
- Modify: `backend/app/services/simulation_manager.py`
- Modify: `backend/app/services/simulation_config_generator.py`
- Modify: `backend/app/services/ontology_generator.py`
- Delete: `backend/app/services/graph_builder.py`
- Delete: `backend/app/services/zep_entity_reader.py`
- Delete: `backend/app/services/zep_tools.py`
- Delete: `backend/app/services/zep_graph_memory_updater.py`
- Delete: `backend/app/utils/zep_paging.py`

- [ ] **Step 1: Update services/__init__.py**

Replace all Zep imports:
```python
from .local_graph_service import LocalGraphService, EntityNode, FilteredEntities, GraphInfo
from .local_graph_tools import LocalGraphToolsService, SearchResult, InsightForgeResult, PanoramaResult, InterviewResult
from .local_graph_memory_updater import LocalGraphMemoryUpdater, LocalGraphMemoryManager, AgentActivity
```

Update `__all__` list accordingly — remove `GraphBuilderService`, `ZepEntityReader`, `ZepGraphMemoryUpdater`, `ZepGraphMemoryManager`. Add `LocalGraphService`, `LocalGraphToolsService`, `LocalGraphMemoryUpdater`, `LocalGraphMemoryManager`.

- [ ] **Step 2: Update simulation_manager.py**

Replace:
```python
from .zep_entity_reader import ZepEntityReader, FilteredEntities
```
With:
```python
from .local_graph_service import LocalGraphService, FilteredEntities
```

Replace any `ZepEntityReader()` instantiations with `LocalGraphService(...)`.

- [ ] **Step 3: Update simulation_config_generator.py**

Replace:
```python
from .zep_entity_reader import EntityNode, ZepEntityReader
```
With:
```python
from .local_graph_service import EntityNode
```

(This file only imports the dataclass, not the service itself.)

- [ ] **Step 4: Update ontology_generator.py**

Find and remove/comment the Zep ontology reference string (line ~303):
```python
'from zep_cloud.external_clients.ontology import EntityModel, EntityText, EdgeModel',
```
Replace with a comment or remove the code generation block that references Zep SDK classes. This is a code-generation string, not an import — update it to reflect the new stack.

- [ ] **Step 5: Delete old Zep files**

```bash
git rm backend/app/services/graph_builder.py
git rm backend/app/services/zep_entity_reader.py
git rm backend/app/services/zep_tools.py
git rm backend/app/services/zep_graph_memory_updater.py
git rm backend/app/utils/zep_paging.py
```

- [ ] **Step 6: Verify no Zep references remain**

Run: `grep -rn "zep\|Zep\|ZEP" backend/app/ --include="*.py" | grep -v "__pycache__"`
Expected: No matches (or only comments/docs).

- [ ] **Step 7: Run all existing tests**

Run: `cd /Users/reasoner/IdeaOrganizer/mirofish-predict/backend && uv run python -m pytest tests/ -v`
Expected: All PASS.

- [ ] **Step 8: Commit**

```bash
git add -A backend/app/services/ backend/app/utils/
git commit -m "feat: complete Zep removal — migrate all imports, delete Zep files"
```

---

## Task 10: Tiered Agents + Action Routing (Strategies 4 & 5)

**Files:**
- Modify: `backend/app/services/simulation_config_generator.py`
- Modify: `backend/scripts/run_twitter_simulation.py`
- Modify: `backend/scripts/run_reddit_simulation.py`
- Modify: `backend/scripts/run_parallel_simulation.py`
- Create: `backend/tests/test_tiered_agents.py`

- [ ] **Step 1: Write test for tier assignment and rule-based action**

Create `backend/tests/test_tiered_agents.py`:
```python
import random


def rule_based_action(agent_config, feed_items):
    """Rule-based action for Tier 2/3 agents."""
    if not feed_items:
        return "DO_NOTHING"
    topics = agent_config.get("interested_topics", [])
    feed_text = " ".join(str(item) for item in feed_items)
    relevance = sum(1 for t in topics if t.lower() in feed_text.lower()) / max(len(topics), 1)
    if relevance > 0.3:
        roll = random.random()
        if roll < 0.4:
            return "LIKE_POST"
        elif roll < 0.6:
            return "REPOST"
        else:
            return "DO_NOTHING"
    return "DO_NOTHING"


class TestTieredAgents:
    def test_rule_based_no_feed_returns_do_nothing(self):
        config = {"interested_topics": ["AI", "Tech"]}
        assert rule_based_action(config, []) == "DO_NOTHING"

    def test_rule_based_relevant_feed_returns_action(self):
        random.seed(42)
        config = {"interested_topics": ["AI", "Tech"]}
        feed = ["AI breakthrough announced today"]
        result = rule_based_action(config, feed)
        assert result in ("LIKE_POST", "REPOST", "DO_NOTHING")

    def test_rule_based_irrelevant_feed_returns_do_nothing(self):
        config = {"interested_topics": ["Cooking", "Music"]}
        feed = ["Political debate continues"]
        assert rule_based_action(config, feed) == "DO_NOTHING"

    def test_tier_assignment_from_influence_weight(self):
        """Agents should be assigned tiers based on influence_weight."""
        agents = [
            {"agent_id": 0, "influence_weight": 2.0},
            {"agent_id": 1, "influence_weight": 1.0},
            {"agent_id": 2, "influence_weight": 0.3},
        ]
        sorted_agents = sorted(agents, key=lambda a: a["influence_weight"], reverse=True)
        total = len(sorted_agents)
        for i, agent in enumerate(sorted_agents):
            ratio = i / total
            if ratio < 0.2:
                agent["tier"] = 1
            elif ratio < 0.5:
                agent["tier"] = 2
            else:
                agent["tier"] = 3
        assert sorted_agents[0]["tier"] == 1
        assert sorted_agents[1]["tier"] == 2
        assert sorted_agents[2]["tier"] == 3
```

- [ ] **Step 2: Run tests**

Run: `cd /Users/reasoner/IdeaOrganizer/mirofish-predict/backend && uv run python -m pytest tests/test_tiered_agents.py -v`
Expected: All PASS (these are self-contained unit tests).

- [ ] **Step 3: Add tier field to simulation_config_generator.py**

In the LLM prompt that generates `agent_configs`, add tier assignment instruction per spec section 2.4. Also add a post-processing step that assigns tier based on `influence_weight` if LLM doesn't provide it:
```python
# After LLM generates agent_configs:
sorted_agents = sorted(agent_configs, key=lambda a: a.get("influence_weight", 1.0), reverse=True)
total = len(sorted_agents)
for i, agent in enumerate(sorted_agents):
    if "tier" not in agent:
        ratio = i / total
        if ratio < 0.2:
            agent["tier"] = 1
        elif ratio < 0.5:
            agent["tier"] = 2
        else:
            agent["tier"] = 3
```

- [ ] **Step 4: Create shared action routing utility + update simulation scripts**

Create `backend/app/utils/action_routing.py` with `rule_based_action()` and `compute_topic_relevance()` functions. This module is imported by all 3 simulation scripts.

In `backend/scripts/run_twitter_simulation.py`, `run_reddit_simulation.py`, and `run_parallel_simulation.py`:

Import from shared module:
```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from app.utils.action_routing import rule_based_action
```

In the round loop where actions are assigned, add tier-based branching:
```python
agent_tier = agent_config.get("tier", 1)
if agent_tier == 1:
    actions[agent] = LLMAction()
elif agent_tier == 2:
    # Only LLM for content creation
    if needs_content_creation(agent, feed):
        actions[agent] = LLMAction()
    else:
        actions[agent] = rule_based_action_as_manual(agent_config, feed)
else:  # tier 3
    actions[agent] = rule_based_action_as_manual(agent_config, feed)
```

Apply same changes to `run_parallel_simulation.py`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/simulation_config_generator.py backend/scripts/run_twitter_simulation.py backend/scripts/run_reddit_simulation.py backend/scripts/run_parallel_simulation.py backend/tests/test_tiered_agents.py
git commit -m "feat: add tiered agents (strategy 4) + rule-based action routing (strategy 5)"
```

---

## Task 11: Convergence Early Stopping (Strategy 6)

**Files:**
- Modify: `backend/scripts/run_twitter_simulation.py`
- Modify: `backend/scripts/run_reddit_simulation.py`
- Modify: `backend/scripts/run_parallel_simulation.py`
- Modify: `backend/tests/test_tiered_agents.py`

- [ ] **Step 1: Write test for convergence detection**

Add to `backend/tests/test_tiered_agents.py`:
```python
import math
from collections import Counter


def compute_action_distribution(actions):
    """Compute normalized action type distribution."""
    counter = Counter(a["action_type"] for a in actions)
    total = sum(counter.values())
    if total == 0:
        return {}
    return {k: v / total for k, v in counter.items()}


def kl_divergence(p, q):
    """KL divergence between two distributions. Returns 0 if identical."""
    if not p or not q:
        return float('inf')
    all_keys = set(p.keys()) | set(q.keys())
    div = 0.0
    for k in all_keys:
        p_val = p.get(k, 1e-10)
        q_val = q.get(k, 1e-10)
        if p_val > 0:
            div += p_val * math.log(p_val / q_val)
    return div


class TestConvergence:
    def test_identical_distributions_zero_divergence(self):
        dist = {"LIKE_POST": 0.5, "DO_NOTHING": 0.5}
        assert kl_divergence(dist, dist) == pytest.approx(0.0)

    def test_different_distributions_positive_divergence(self):
        p = {"LIKE_POST": 0.9, "DO_NOTHING": 0.1}
        q = {"LIKE_POST": 0.1, "DO_NOTHING": 0.9}
        assert kl_divergence(p, q) > 0.5

    def test_compute_action_distribution(self):
        actions = [
            {"action_type": "LIKE_POST"},
            {"action_type": "LIKE_POST"},
            {"action_type": "DO_NOTHING"},
        ]
        dist = compute_action_distribution(actions)
        assert dist["LIKE_POST"] == pytest.approx(2/3)
        assert dist["DO_NOTHING"] == pytest.approx(1/3)
```

- [ ] **Step 2: Run tests**

Run: `cd /Users/reasoner/IdeaOrganizer/mirofish-predict/backend && uv run python -m pytest tests/test_tiered_agents.py::TestConvergence -v`
Expected: All PASS.

- [ ] **Step 3: Add convergence check to simulation scripts**

In `run_twitter_simulation.py` and `run_reddit_simulation.py`, add the convergence check inside the round loop per spec section 2.6. Import `CONVERGENCE_THRESHOLD` and `CONVERGENCE_CHECK_INTERVAL` from config (passed via simulation_config.json or environment).

```python
previous_checkpoint_dist = None
for round_num in range(total_rounds):
    # ... existing round logic ...

    # Convergence check
    check_interval = int(os.environ.get("CONVERGENCE_CHECK_INTERVAL", "5"))
    threshold = float(os.environ.get("CONVERGENCE_THRESHOLD", "0.05"))
    if round_num % check_interval == 0 and round_num > 0:
        recent_actions = load_recent_actions(round_num, last_n=check_interval)
        current_dist = compute_action_distribution(recent_actions)
        if previous_checkpoint_dist is not None:
            div = kl_divergence(current_dist, previous_checkpoint_dist)
            if div < threshold:
                print(f"Round {round_num}: convergence detected (KL={div:.4f}), stopping")
                break
        previous_checkpoint_dist = current_dist
```

- [ ] **Step 4: Commit**

```bash
git add backend/scripts/run_twitter_simulation.py backend/scripts/run_reddit_simulation.py backend/scripts/run_parallel_simulation.py backend/tests/test_tiered_agents.py
git commit -m "feat: add convergence early stopping (strategy 6)"
```

---

## Task 12: Final Verification

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite**

Run: `cd /Users/reasoner/IdeaOrganizer/mirofish-predict/backend && uv run python -m pytest tests/ -v`
Expected: All tests PASS.

- [ ] **Step 2: Verify zero Zep references in Python source**

Run: `grep -rn "zep_cloud\|from zep\|import zep\|ZEP_API_KEY" backend/app/ backend/scripts/ --include="*.py" | grep -v __pycache__`
Expected: No matches.

- [ ] **Step 3: Verify Flask app starts**

Run: `cd /Users/reasoner/IdeaOrganizer/mirofish-predict/backend && timeout 5 uv run python run.py || true`
Expected: Flask starts without import errors (will timeout after 5s, that's fine).

- [ ] **Step 4: Final commit if any fixes needed**

```bash
git add -A && git commit -m "fix: final cleanup after local stack migration"
```
