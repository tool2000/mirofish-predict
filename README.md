<div align="center">

<img src="./static/image/MiroFish_logo_compressed.jpeg" alt="MiroFish Logo" width="75%"/>

</br>
<em>완전 로컬 기반 멀티 에이전트 군집 지능 예측 엔진</em>

[![GitHub Stars](https://img.shields.io/github/stars/666ghj/MiroFish?style=flat-square&color=DAA520)](https://github.com/666ghj/MiroFish/stargazers)
[![GitHub Forks](https://img.shields.io/github/forks/666ghj/MiroFish?style=flat-square)](https://github.com/666ghj/MiroFish/network)
[![Docker](https://img.shields.io/badge/Docker-Build-2496ED?style=flat-square&logo=docker&logoColor=white)](https://hub.docker.com/)

[한국어](./README.md) | [English](./README-EN.md) | [中文](./README-ZH.md)

</div>

## 개요

**MiroFish**는 멀티 에이전트 기술로 구동되는 AI 예측 엔진입니다. 속보, 정책 초안, 금융 신호, 소설 텍스트 등의 시드 정보를 입력하면 고충실도 디지털 세계를 자동으로 구성하고, 수백 개의 지능형 에이전트가 소셜 미디어 환경에서 자유롭게 상호작용하며 미래 시나리오를 시뮬레이션합니다.

**이 포크는 완전 로컬 실행에 최적화된 버전입니다.** 클라우드 API 의존성(Zep Cloud, OpenAI API 등)을 모두 제거하고, 로컬 LLM(llama.cpp) + 로컬 그래프 DB(Kuzu) + 로컬 지식그래프 추출(kg-gen)로 전환했습니다. 또한 6가지 비용 최적화 전략을 적용하여 시뮬레이션 비용을 90% 이상 절감합니다.

> 사용자가 할 일은 단 두 가지입니다: 시드 자료를 업로드하고, 자연어로 예측 요구사항을 설명하세요.
> MiroFish가 반환하는 결과: 상세한 예측 리포트와 깊이 있게 상호작용 가능한 디지털 세계

## 원본 대비 주요 변경사항

| 영역 | 원본 (MiroFish) | 이 버전 (mirofish-predict) |
|------|----------------|--------------------------|
| **LLM** | OpenAI / Alibaba Cloud API | 로컬 llama.cpp (OpenAI 호환 API) |
| **지식 그래프** | Zep Cloud (클라우드) | kg-gen + Kuzu DB (로컬 임베디드) |
| **페르소나** | 2,000자 자유 서술 | 300자 구조화 태그 (토큰 80% 절감) |
| **에이전트 구조** | 전원 LLM 기반 | 계층적 3-Tier (핵심 20% LLM, 나머지 규칙 기반) |
| **시뮬레이션** | 고정 라운드 | KL-divergence 수렴 감지 → 조기 종료 |
| **비용** | API 호출 비용 발생 | 완전 무료 (로컬 GPU 사용) |

## 아키텍처

```
┌─────────────────────────────────────────────────────────┐
│                    Vue 3 Frontend                        │
│                  http://localhost:3000                    │
└──────────────────────┬──────────────────────────────────┘
                       │ REST API
┌──────────────────────▼──────────────────────────────────┐
│                   Flask Backend                          │
│                  http://localhost:5001                    │
│                                                          │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ LocalGraph   │  │ OasisProfile │  │ LocalGraph     │  │
│  │ Service      │  │ Generator    │  │ ToolsService   │  │
│  │ (kg-gen +   │  │ (300자 압축) │  │ (Cypher 검색)  │  │
│  │  Kuzu DB)   │  │              │  │                │  │
│  └──────┬──────┘  └──────┬───────┘  └───────┬────────┘  │
│         │                │                  │            │
│  ┌──────▼────────────────▼──────────────────▼────────┐  │
│  │              로컬 llama.cpp 서버                    │  │
│  │           http://localhost:8080/v1                  │  │
│  │         (OpenAI 호환 API 엔드포인트)                │  │
│  └───────────────────────────────────────────────────┘  │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │           OASIS 시뮬레이션 엔진                     │  │
│  │  ┌─────────┐ ┌─────────┐ ┌──────────────────────┐ │  │
│  │  │ Tier 1  │ │ Tier 2  │ │ Tier 3 (규칙 기반)   │ │  │
│  │  │ LLM     │ │ 하이브리│ │ 확률적 행동          │ │  │
│  │  │ (20%)   │ │ 드(30%) │ │ (50%)               │ │  │
│  │  └─────────┘ └─────────┘ └──────────────────────┘ │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

## 워크플로우

1. **시드 문서 업로드**: PDF, Markdown, TXT 파일을 업로드합니다
2. **지식 그래프 구축**: kg-gen이 엔터티와 관계를 추출하고, Kuzu DB에 저장합니다
3. **에이전트 페르소나 생성**: 엔터티별 구조화된 300자 캐릭터 태그를 LLM으로 생성합니다
4. **병렬 시뮬레이션**: Twitter/Reddit 환경에서 계층적 에이전트가 상호작용합니다
5. **수렴 감지**: 에이전트 행동 분포가 수렴하면 자동으로 시뮬레이션을 종료합니다
6. **리포트 생성**: ReportAgent가 그래프 도구로 시뮬레이션 결과를 분석합니다

## 빠른 시작

### 사전 요구사항

| 도구 | 버전 | 설명 | 설치 확인 |
|------|------|------|----------|
| **Node.js** | 18+ | 프런트엔드 런타임 | `node -v` |
| **Python** | 3.11+ | 백엔드 런타임 | `python --version` |
| **uv** | 최신 | Python 패키지 매니저 | `uv --version` |
| **llama.cpp** | 최신 | 로컬 LLM 서버 | `llama-server --version` |
| **GPU** | VRAM 8GB+ | LLM 추론 (CPU도 가능하나 느림) | - |

### 1. llama.cpp 서버 시작

원하는 모델을 다운로드하고 OpenAI 호환 서버를 시작합니다:

```bash
# GGUF 모델 다운로드 (예: Qwen2.5-7B)
# https://huggingface.co/models?search=gguf 에서 선택

# llama.cpp 서버 시작 (프리픽스 캐싱 활성화)
llama-server \
  -m your-model.gguf \
  --host 0.0.0.0 \
  --port 8080 \
  --cache-type-k f16 \
  --cache-type-v f16 \
  -ngl 99
```

서버가 시작되면 `http://localhost:8080/v1`에서 OpenAI 호환 API를 제공합니다.

### 2. 환경 변수 설정

```bash
cp .env.example .env
```

`.env` 파일 내용:

```env
# LLM 설정 (llama.cpp 서버)
LLM_API_KEY=not-needed
LLM_BASE_URL=http://localhost:8080/v1
LLM_MODEL_NAME=local-model

# kg-gen 설정 (동일한 llama.cpp 서버 사용)
KGGEN_MODEL=openai/local-model

# Kuzu DB 경로 (기본값 사용 가능)
# KUZU_DB_DIR=backend/data/kuzu_db

# 시뮬레이션 최적화 (기본값 사용 가능)
# CONVERGENCE_THRESHOLD=0.05
# CONVERGENCE_CHECK_INTERVAL=5
```

### 3. 의존성 설치

```bash
# 전체 설치 (프런트엔드 + 백엔드)
npm run setup:all
```

또는 단계별:

```bash
npm run setup          # Node 의존성
npm run setup:backend  # Python 의존성 (kg-gen, kuzu, OASIS 등)
```

### 4. 서비스 시작

```bash
# 프런트엔드 + 백엔드 동시 시작
npm run dev
```

| 서비스 | URL |
|--------|-----|
| 프런트엔드 | http://localhost:3000 |
| 백엔드 API | http://localhost:5001 |
| llama.cpp | http://localhost:8080/v1 |

개별 실행:

```bash
npm run backend   # 백엔드만
npm run frontend  # 프런트엔드만
```

### Docker 배포

```bash
cp .env.example .env
# .env에 LLM_BASE_URL을 호스트의 llama.cpp 서버 주소로 설정
# Docker 내부에서 호스트 접근: http://host.docker.internal:8080/v1

docker compose up -d
```

## 최적화 전략

이 버전에 적용된 6가지 최적화 전략:

| # | 전략 | 효과 | 적용 방법 |
|---|------|------|----------|
| 1 | **페르소나 압축** | 입력 토큰 80% 절감 | 2,000자 → 300자 구조화 태그 |
| 2 | **프리픽스 캐싱** | KV Cache 재사용 20% 절감 | llama.cpp `--cache-type-k/v f16` |
| 3 | **단일 플랫폼** | LLM 호출 50% 절감 | `--twitter-only` 또는 `--reddit-only` |
| 4 | **계층적 에이전트** | LLM 호출 55% 절감 | Tier 1(20% LLM) / Tier 2(30%) / Tier 3(50% 규칙) |
| 5 | **액션 라우팅** | 추가 30% 절감 | LIKE/DO_NOTHING은 규칙 기반 |
| 6 | **수렴 조기종료** | 라운드 25% 절감 | KL-divergence < 0.05 → 종료 |

### 예상 효과 (100명 x 30라운드 기준)

| 항목 | 최적화 전 | 최적화 후 |
|------|----------|----------|
| LLM 호출 | ~18,000건 | ~1,500건 |
| 입력 토큰 | ~36M | ~1.5M |

## 기술 스택

| 계층 | 기술 |
|------|------|
| **프런트엔드** | Vue 3 |
| **백엔드** | Flask 3.0+, Python 3.11+ |
| **LLM** | llama.cpp (OpenAI 호환 API) |
| **지식 그래프** | kg-gen (추출) + Kuzu DB (저장/쿼리) |
| **시뮬레이션** | CAMEL-OASIS |
| **패키지 관리** | uv (Python), npm (Node) |

## 프로젝트 구조

```
mirofish-predict/
├── backend/
│   ├── app/
│   │   ├── api/                          # Flask API 라우트
│   │   ├── services/
│   │   │   ├── local_graph_service.py    # kg-gen + Kuzu 통합 서비스
│   │   │   ├── local_graph_tools.py      # 리포트 에이전트 도구
│   │   │   ├── local_graph_memory_updater.py  # 시뮬레이션 메모리
│   │   │   ├── oasis_profile_generator.py     # 에이전트 페르소나 생성
│   │   │   ├── report_agent.py           # ReACT 리포트 생성
│   │   │   └── ...
│   │   ├── utils/
│   │   │   ├── action_routing.py         # 규칙 기반 액션 + 수렴 감지
│   │   │   ├── llm_client.py             # OpenAI 호환 LLM 클라이언트
│   │   │   └── ...
│   │   └── config.py                     # 설정 (로컬 기본값)
│   ├── scripts/                          # 시뮬레이션 실행 스크립트
│   ├── tests/                            # 87개 테스트
│   └── pyproject.toml
├── frontend/                             # Vue 3 프런트엔드
├── docs/superpowers/
│   ├── specs/                            # 설계 문서
│   └── plans/                            # 구현 계획
└── docker-compose.yml
```

## 환경 변수 참조

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `LLM_API_KEY` | `not-needed` | LLM API 키 (로컬이면 아무 값) |
| `LLM_BASE_URL` | `http://localhost:8080/v1` | LLM 서버 주소 |
| `LLM_MODEL_NAME` | `local-model` | 모델 이름 |
| `KGGEN_MODEL` | `openai/local-model` | kg-gen용 모델 (LiteLLM 포맷) |
| `KUZU_DB_DIR` | `backend/data/kuzu_db` | Kuzu DB 저장 경로 |
| `CONVERGENCE_THRESHOLD` | `0.05` | 수렴 판정 KL-divergence 임계값 |
| `CONVERGENCE_CHECK_INTERVAL` | `5` | 수렴 체크 라운드 간격 |

## 감사의 글

이 프로젝트는 [MiroFish](https://github.com/666ghj/MiroFish)를 포크하여 로컬 실행에 최적화한 버전입니다.

- **[OASIS](https://github.com/camel-ai/oasis)** — 소셜 미디어 시뮬레이션 엔진 (CAMEL-AI)
- **[kg-gen](https://github.com/stair-lab/kg-gen)** — 텍스트 기반 지식 그래프 추출 (STAIR Lab)
- **[Kuzu](https://github.com/kuzudb/kuzu)** — 임베디드 그래프 데이터베이스

## 라이선스

AGPL-3.0
