"""
Report Agent
LangChain + ZepReACT시뮬레이션보고서 생성

:
1. 시뮬레이션Zep그래프정보생성보고서
2. 디렉터리, 생성
3. ReACT
4. , 호출도구
"""

import os
import json
import time
import re
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from ..config import Config
from ..utils.llm_client import LLMClient
from ..utils.logger import get_logger
from .local_graph_tools import (
    LocalGraphToolsService,
    SearchResult,
    InsightForgeResult,
    PanoramaResult,
    InterviewResult
)

logger = get_logger('mirofish.report_agent')


class ReportLogger:
    """
    Report Agent 상세로그
    
    보고서파일 처리 중agent_log.jsonl 파일, 상세.
     JSON , , 타입, 상세.
    """
    
    def __init__(self, report_id: str):
        """
        로그
        
        Args:
            report_id: 보고서ID, 로그파일
        """
        self.report_id = report_id
        self.log_file_path = os.path.join(
            Config.UPLOAD_FOLDER, 'reports', report_id, 'agent_log.jsonl'
        )
        self.start_time = datetime.now()
        self._ensure_log_file()
    
    def _ensure_log_file(self):
        """로그파일디렉터리"""
        log_dir = os.path.dirname(self.log_file_path)
        os.makedirs(log_dir, exist_ok=True)
    
    def _get_elapsed_time(self) -> float:
        """시작()"""
        return (datetime.now() - self.start_time).total_seconds()
    
    def log(
        self, 
        action: str, 
        stage: str,
        details: Dict[str, Any],
        section_title: str = None,
        section_index: int = None
    ):
        """
        로그
        
        Args:
            action: 타입,  'start', 'tool_call', 'llm_response', 'section_complete' 
            stage: 현재,  'planning', 'generating', 'completed'
            details: 상세, 
            section_title: 현재섹션(선택)
            section_index: 현재섹션(선택)
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "elapsed_seconds": round(self._get_elapsed_time(), 2),
            "report_id": self.report_id,
            "action": action,
            "stage": stage,
            "section_title": section_title,
            "section_index": section_index,
            "details": details
        }
        
        # 쓰기 JSONL 파일
        with open(self.log_file_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
    
    def log_start(self, simulation_id: str, graph_id: str, simulation_requirement: str):
        """보고서 생성시작"""
        self.log(
            action="report_start",
            stage="pending",
            details={
                "simulation_id": simulation_id,
                "graph_id": graph_id,
                "simulation_requirement": simulation_requirement,
                "message": "보고서 생성작업 시작"
            }
        )
    
    def log_planning_start(self):
        """시작"""
        self.log(
            action="planning_start",
            stage="planning",
            details={"message": "시작보고서"}
        )
    
    def log_planning_context(self, context: Dict[str, Any]):
        """정보"""
        self.log(
            action="planning_context",
            stage="planning",
            details={
                "message": "시뮬레이션정보",
                "context": context
            }
        )
    
    def log_planning_complete(self, outline_dict: Dict[str, Any]):
        """완료"""
        self.log(
            action="planning_complete",
            stage="planning",
            details={
                "message": "완료",
                "outline": outline_dict
            }
        )
    
    def log_section_start(self, section_title: str, section_index: int):
        """섹션생성시작"""
        self.log(
            action="section_start",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={"message": f"시작생성섹션: {section_title}"}
        )
    
    def log_react_thought(self, section_title: str, section_index: int, iteration: int, thought: str):
        """ ReACT """
        self.log(
            action="react_thought",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "thought": thought,
                "message": f"ReACT {iteration}"
            }
        )
    
    def log_tool_call(
        self, 
        section_title: str, 
        section_index: int,
        tool_name: str, 
        parameters: Dict[str, Any],
        iteration: int
    ):
        """도구 호출"""
        self.log(
            action="tool_call",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "tool_name": tool_name,
                "parameters": parameters,
                "message": f"도구 호출: {tool_name}"
            }
        )
    
    def log_tool_result(
        self,
        section_title: str,
        section_index: int,
        tool_name: str,
        result: str,
        iteration: int
    ):
        """도구 호출(, )"""
        self.log(
            action="tool_result",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "tool_name": tool_name,
                "result": result,  # , 
                "result_length": len(result),
                "message": f"도구 {tool_name} 반환"
            }
        )
    
    def log_llm_response(
        self,
        section_title: str,
        section_index: int,
        response: str,
        iteration: int,
        has_tool_calls: bool,
        has_final_answer: bool
    ):
        """ LLM (, )"""
        self.log(
            action="llm_response",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "response": response,  # , 
                "response_length": len(response),
                "has_tool_calls": has_tool_calls,
                "has_final_answer": has_final_answer,
                "message": f"LLM  (도구 호출: {has_tool_calls}, : {has_final_answer})"
            }
        )
    
    def log_section_content(
        self,
        section_title: str,
        section_index: int,
        content: str,
        tool_calls_count: int
    ):
        """섹션생성완료(, 섹션완료)"""
        self.log(
            action="section_content",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "content": content,  # , 
                "content_length": len(content),
                "tool_calls_count": tool_calls_count,
                "message": f"섹션 {section_title} 생성완료"
            }
        )
    
    def log_section_full_complete(
        self,
        section_title: str,
        section_index: int,
        full_content: str
    ):
        """
        섹션생성완료

        로그섹션완료, 
        """
        self.log(
            action="section_complete",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "content": full_content,
                "content_length": len(full_content),
                "message": f"섹션 {section_title} 생성완료"
            }
        )
    
    def log_report_complete(self, total_sections: int, total_time_seconds: float):
        """보고서 생성완료"""
        self.log(
            action="report_complete",
            stage="completed",
            details={
                "total_sections": total_sections,
                "total_time_seconds": round(total_time_seconds, 2),
                "message": "보고서 생성완료"
            }
        )
    
    def log_error(self, error_message: str, stage: str, section_title: str = None):
        """오류"""
        self.log(
            action="error",
            stage=stage,
            section_title=section_title,
            section_index=None,
            details={
                "error": error_message,
                "message": f"오류: {error_message}"
            }
        )


class ReportConsoleLogger:
    """
    Report Agent 콘솔로그
    
    콘솔로그(INFO, WARNING)쓰기보고서파일 처리 중onsole_log.txt 파일.
    로그 agent_log.jsonl , 콘솔.
    """
    
    def __init__(self, report_id: str):
        """
        콘솔로그
        
        Args:
            report_id: 보고서ID, 로그파일
        """
        self.report_id = report_id
        self.log_file_path = os.path.join(
            Config.UPLOAD_FOLDER, 'reports', report_id, 'console_log.txt'
        )
        self._ensure_log_file()
        self._file_handler = None
        self._setup_file_handler()
    
    def _ensure_log_file(self):
        """로그파일디렉터리"""
        log_dir = os.path.dirname(self.log_file_path)
        os.makedirs(log_dir, exist_ok=True)
    
    def _setup_file_handler(self):
        """파일, 로그쓰기파일"""
        import logging
        
        # 파일
        self._file_handler = logging.FileHandler(
            self.log_file_path,
            mode='a',
            encoding='utf-8'
        )
        self._file_handler.setLevel(logging.INFO)
        
        # 콘솔
        formatter = logging.Formatter(
            '[%(asctime)s] %(levelname)s: %(message)s',
            datefmt='%H:%M:%S'
        )
        self._file_handler.setFormatter(formatter)
        
        #  report_agent  logger
        loggers_to_attach = [
            'mirofish.report_agent',
            'mirofish.local_graph_tools',
        ]
        
        for logger_name in loggers_to_attach:
            target_logger = logging.getLogger(logger_name)
            # 
            if self._file_handler not in target_logger.handlers:
                target_logger.addHandler(self._file_handler)
    
    def close(self):
        """파일 로거를 정리하고 핸들러를 해제한다."""
        import logging
        
        if self._file_handler:
            loggers_to_detach = [
                'mirofish.report_agent',
                'mirofish.local_graph_tools',
            ]
            
            for logger_name in loggers_to_detach:
                target_logger = logging.getLogger(logger_name)
                if self._file_handler in target_logger.handlers:
                    target_logger.removeHandler(self._file_handler)
            
            self._file_handler.close()
            self._file_handler = None
    
    def __del__(self):
        """파일"""
        self.close()


class ReportStatus(str, Enum):
    """보고서상태"""
    PENDING = "pending"
    PLANNING = "planning"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ReportSection:
    """보고서섹션"""
    title: str
    content: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "content": self.content
        }

    def to_markdown(self, level: int = 2) -> str:
        """Markdown"""
        md = f"{'#' * level} {self.title}\n\n"
        if self.content:
            md += f"{self.content}\n\n"
        return md


@dataclass
class ReportOutline:
    """보고서"""
    title: str
    summary: str
    sections: List[ReportSection]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "sections": [s.to_dict() for s in self.sections]
        }
    
    def to_markdown(self) -> str:
        """Markdown"""
        md = f"# {self.title}\n\n"
        md += f"> {self.summary}\n\n"
        for section in self.sections:
            md += section.to_markdown()
        return md


@dataclass
class Report:
    """보고서"""
    report_id: str
    simulation_id: str
    graph_id: str
    simulation_requirement: str
    status: ReportStatus
    outline: Optional[ReportOutline] = None
    markdown_content: str = ""
    created_at: str = ""
    completed_at: str = ""
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "simulation_id": self.simulation_id,
            "graph_id": self.graph_id,
            "simulation_requirement": self.simulation_requirement,
            "status": self.status.value,
            "outline": self.outline.to_dict() if self.outline else None,
            "markdown_content": self.markdown_content,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "error": self.error
        }


# ═══════════════════════════════════════════════════════════════
# Prompt
# ═══════════════════════════════════════════════════════════════

# ── 도구 설명 ──

TOOL_DESC_INSIGHT_FORGE = """\
[심층 분석 도구]
질문 하나를 깊이 파고들어 근거 중심 분석을 수행합니다.

주요 기능:
1. 질문 의도와 핵심 쟁점 정리
2. 시뮬레이션 그래프에서 관련 엔터티/관계 추적
3. 사실 검색, 엔터티 분석, 관계 흐름 해석
4. 보고서에 바로 반영할 수 있는 인사이트 반환

적합한 사용 상황:
- 원인/맥락 분석이 필요한 질문
- 특정 주장에 대한 근거 검증
- 보고서 섹션의 핵심 논점 정리

반환 결과:
- 근거 사실(출처 포함)
- 핵심 엔터티
- 관계 흐름과 해석
"""

TOOL_DESC_PANORAMA_SEARCH = """\
[전역 탐색 도구]
시뮬레이션 그래프를 폭넓게 훑어 현재 상태를 빠르게 파악합니다.

주요 기능:
1. 노드/관계의 전체 분포 확인
2. 현재 유효 사실과 과거/만료 사실 구분 조회
3. 엔터티 관계의 전반적 구조 파악

적합한 사용 상황:
- 현황 요약이 필요할 때
- 탐색 초기 단계에서 큰 그림을 잡을 때
- 인터뷰 전 대상/맥락을 빠르게 훑을 때

반환 결과:
- 현재 유효 사실
- 과거/만료 사실
- 엔터티 및 관계 요약
"""

TOOL_DESC_QUICK_SEARCH = """\
[빠른 조회 도구]
특정 키워드나 조건으로 사실을 즉시 조회하는 경량 검색 도구입니다.

적합한 사용 상황:
- 숫자/사실을 빠르게 확인할 때
- 특정 엔터티 관련 정보를 단건 확인할 때
- 이미 가설이 있고 증거만 보강하면 될 때

반환 결과:
- 조회된 사실 목록
"""

TOOL_DESC_INTERVIEW_AGENTS = """\
[에이전트 인터뷰 도구(플랫폼 기반)]
OASIS 시뮬레이션 인터뷰 API를 호출해 실행 중 시뮬레이션의 에이전트를 인터뷰합니다.
Twitter/Reddit 플랫폼 맥락을 반영한 답변을 수집할 수 있습니다.

주요 기능:
1. 시뮬레이션 에이전트 목록 확인
2. 인터뷰 대상 및 주제 선정(행동, 인식, 감정, 전략 등)
3. 인터뷰 질문 생성
4. `/api/simulation/interview/batch` API 호출
5. 인터뷰 응답 분석 및 보고서 반영

적합한 사용 상황:
- "왜 그렇게 행동했는가?" 같은 동기 분석이 필요할 때
- 플랫폼별 반응 차이를 비교할 때
- 보고서에 인터뷰 기반 근거를 추가할 때

반환 결과:
- 인터뷰 대상 에이전트 정보
- 플랫폼별 인터뷰 응답
- 핵심 인사이트(직접 인용 포함)
- 인터뷰 결과 요약

주의: OASIS 시뮬레이션이 실행 중일 때만 사용 가능합니다.
"""

# ── 보고서 개요 생성 프롬프트 ──

PLAN_SYSTEM_PROMPT = """\
당신은 시뮬레이션 보고서 설계를 담당하는 분석가입니다.
목표는 "실제 시뮬레이션에서 관찰된 현상"을 중심으로 보고서 목차를 만드는 것입니다.

[핵심 원칙]
- 시뮬레이션에서 실제로 관찰 가능한 사실을 중심으로 구성합니다.
- "무엇이 일어났는지"와 "에이전트가 어떻게 반응했는지"를 우선합니다.
- 일반론, 이론 설명, 교과서식 배경지식은 배제합니다.

[작업]
다음 정보를 바탕으로 보고서 개요(JSON)를 생성하세요.
1. 어떤 현상/변화/패턴을 다룰지
2. 어떤 에이전트 그룹 또는 행위 주체를 조명할지
3. 시뮬레이션 요구사항과 직접 연결되는지

[구성 제약]
- 섹션 수는 2개 이상 5개 이하
- 섹션 제목은 구체적이고 중복되지 않게 작성
- 각 섹션 설명은 "해당 섹션에서 무엇을 검증/설명할지"를 분명히 기술

반드시 아래 JSON 형식만 출력하세요:
{
  "title": "보고서 제목",
  "summary": "보고서 한 줄 요약",
  "sections": [
    {
      "title": "섹션 제목",
      "description": "섹션 설명"
    }
  ]
}
"""

PLAN_USER_PROMPT_TEMPLATE = """\
[요청]
시뮬레이션 요구사항: {simulation_requirement}

[시뮬레이션 개요]
- 총 엔터티 수: {total_nodes}
- 총 관계 수: {total_edges}
- 엔터티 유형: {entity_types}
- 에이전트 수: {total_entities}

[관련 사실 데이터]
{related_facts_json}

위 정보를 근거로 보고서 개요를 설계해 주세요.
핵심 질문:
1. 지금 시뮬레이션에서 가장 중요한 변화/현상은 무엇인가?
2. 어떤 에이전트(또는 집단)에 집중해야 의미 있는가?
3. 요구사항에 가장 직접적으로 답하는 섹션 구조는 무엇인가?

섹션 수는 반드시 2~5개 범위로 유지하세요.
"""

# ── 섹션 생성 프롬프트 ──

SECTION_SYSTEM_PROMPT_TEMPLATE = """\
당신은 시뮬레이션 보고서 작성 에이전트입니다.
아래 정보에 맞춰 현재 섹션 본문만 작성하세요.

보고서 제목: {report_title}
보고서 요약: {report_summary}
시뮬레이션 요구사항: {simulation_requirement}
현재 섹션 제목: {section_title}

═══════════════════════════════════════════════════════════════
[작성 원칙]
═══════════════════════════════════════════════════════════════

- 시뮬레이션에서 실제로 관찰된 내용만 사용합니다.
- 에이전트의 행동, 반응, 상호작용을 구체적으로 설명합니다.
- 반드시 도구를 호출해 근거를 확보한 뒤 작성합니다.
- 추측성 표현, 일반론, 근거 없는 단정은 금지합니다.

═══════════════════════════════════════════════════════════════
[도구 사용 규칙]
═══════════════════════════════════════════════════════════════

1. 섹션당 최소 3회, 최대 5회 도구를 호출하세요.
2. 가능하면 서로 다른 도구를 조합해 교차 검증하세요.
3. 도구 결과(Observation)를 확인한 뒤 다음 행동을 결정하세요.
4. 충분한 근거가 쌓이면 "Final Answer:"로 섹션 본문을 제출하세요.

사용 가능한 도구:
{tools_description}

도구 요약:
- insight_forge: 질문을 깊게 분석하고 근거를 구조화
- panorama_search: 전역 탐색으로 전체 맥락 확보
- quick_search: 특정 사실을 빠르게 확인
- interview_agents: 시뮬레이션 에이전트 인터뷰 수행

═══════════════════════════════════════════════════════════════
[응답 형식(ReACT)]
═══════════════════════════════════════════════════════════════

A) 도구 호출이 필요할 때:
<tool_call>
{{"name": "도구명", "parameters": {{"파라미터명": "값"}}}}
</tool_call>

B) 충분한 근거를 확보했을 때:
Final Answer:
섹션 본문...

주의:
- 도구 호출과 Final Answer를 한 응답에 함께 쓰지 마세요.
- Observation 없이 연속으로 도구를 호출하지 마세요.

═══════════════════════════════════════════════════════════════
[최종 섹션 출력 규칙]
═══════════════════════════════════════════════════════════════

1. 섹션 "내용"만 출력하고, 제목/헤더는 쓰지 마세요.
2. Markdown 헤더(`#`, `##`, `###`, `####`)는 금지합니다.
3. 필요하면 굵게, 목록, 인용문(>)을 사용하세요.
4. 인용문은 반드시 줄바꿈 후 독립 블록으로 작성하세요.

올바른 예:
현상 요약을 먼저 제시합니다.

> "핵심 발언 또는 데이터 인용"

이 인용이 의미하는 바를 해석합니다.
"""

SECTION_USER_PROMPT_TEMPLATE = """\
이미 작성된 섹션(참고용):
{previous_content}

═══════════════════════════════════════════════════════════════
[현재 작업] 섹션: {section_title}
═══════════════════════════════════════════════════════════════

지침:
1. 기존 섹션과 중복되지 않게 작성하세요.
2. 먼저 도구 호출로 근거를 수집하세요.
3. 근거 기반으로만 섹션 본문을 작성하세요.
4. 최종 출력은 "Final Answer:" 형식으로 제출하세요.

주의:
- `#`, `##`, `###`, `####` 헤더 금지
- "{section_title}" 같은 제목 문구 반복 금지
- 본문 내용만 자연스럽게 작성
"""

# ── ReACT 메시지 ──

REACT_OBSERVATION_TEMPLATE = """\
Observation(도구 실행 결과):

═══ {tool_name} 결과 ═══
{result}

═══════════════════════════════════════════════════════════════
도구 호출 횟수: {tool_calls_count}/{max_tool_calls} (사용: {used_tools_str}){unused_hint}
- 다음 단계에서 필요 시 추가 도구를 호출하세요.
- 근거가 충분하면 "Final Answer:"로 섹션 본문을 제출하세요.
═══════════════════════════════════════════════════════════════"""

REACT_INSUFFICIENT_TOOLS_MSG = (
    "현재 도구 호출이 {tool_calls_count}회로 최소 권장 {min_tool_calls}회에 못 미칩니다. "
    "근거 보강을 위해 도구를 더 호출한 뒤 Final Answer를 작성하세요.{unused_hint}"
)

REACT_INSUFFICIENT_TOOLS_MSG_ALT = (
    "도구 호출 수가 부족합니다({tool_calls_count}/{min_tool_calls}). "
    "추가 도구 호출로 근거를 확보해 주세요.{unused_hint}"
)

REACT_TOOL_LIMIT_MSG = (
    "도구 호출 한도({tool_calls_count}/{max_tool_calls})에 도달했습니다. "
    '"Final Answer:" 형식으로 섹션 본문을 작성하세요.'
)

REACT_UNUSED_TOOLS_HINT = "\n참고: 아직 사용하지 않은 도구가 있습니다: {unused_list}"

REACT_FORCE_FINAL_MSG = "도구 호출 단계를 마쳤습니다. Final Answer로 섹션 본문을 제출하세요."

# ── Chat 프롬프트 ──

CHAT_SYSTEM_PROMPT_TEMPLATE = """\
당신은 시뮬레이션 분석 보조 에이전트입니다.

[시뮬레이션 요구사항]
{simulation_requirement}

[이미 생성된 분석 보고서]
{report_content}

[응답 원칙]
1. 사용자의 질문에 보고서 내용을 바탕으로 답하세요.
2. 보고서만으로 부족하면 도구를 호출해 사실을 보강하세요.
3. 답변은 간결하되 핵심 근거를 명확히 제시하세요.
4. 필요 시 인용문(>)이나 목록으로 가독성을 높이세요.

[사용 가능한 도구] (필요할 때 1~2회 호출)
{tools_description}

[도구 호출 형식]
<tool_call>
{{"name": "도구명", "parameters": {{"파라미터명": "값"}}}}
</tool_call>

[최종 답변 형식]
- 질문에 직접 답변
- 필요하면 핵심 근거를 함께 제시
- 과도한 장황함 없이 명확하게 작성
"""

CHAT_OBSERVATION_SUFFIX = "\n\n위 도구 결과를 반영해 질문에 답변하세요."


# ═══════════════════════════════════════════════════════════════
# ReportAgent 
# ═══════════════════════════════════════════════════════════════


class ReportAgent:
    """
    시뮬레이션 보고서를 생성하는 에이전트.

    ReACT(Reasoning + Acting):
    1. 분석: 시뮬레이션 데이터와 보고서 맥락을 해석
    2. 실행: 도구를 호출해 근거를 수집
    3. 작성: 섹션별 최종 본문 생성
    """
    
    # 도구 호출(섹션)
    MAX_TOOL_CALLS_PER_SECTION = 5
    
    # 리플렉션 최대 횟수
    MAX_REFLECTION_ROUNDS = 3
    
    # 채팅 응답당 도구 호출 한도
    MAX_TOOL_CALLS_PER_CHAT = 2
    
    def __init__(
        self, 
        graph_id: str,
        simulation_id: str,
        simulation_requirement: str,
        llm_client: Optional[LLMClient] = None,
        graph_tools: Optional[LocalGraphToolsService] = None
    ):
        """
        ReportAgent를 초기화한다.

        Args:
            graph_id: 그래프 ID
            simulation_id: 시뮬레이션 ID
            simulation_requirement: 시뮬레이션 요구사항
            llm_client: LLM 클라이언트(선택)
            graph_tools: 그래프 도구 서비스(선택)
        """
        self.graph_id = graph_id
        self.simulation_id = simulation_id
        self.simulation_requirement = simulation_requirement

        self.llm = llm_client or LLMClient()
        self.graph_tools = graph_tools or LocalGraphToolsService()
        
        # 사용 가능한 도구 정의
        self.tools = self._define_tools()
        
        # 리포트 생성 로그 핸들러
        self.report_logger: Optional[ReportLogger] = None
        # 콘솔 출력 로그 핸들러
        self.console_logger: Optional[ReportConsoleLogger] = None
        
        logger.info(f"ReportAgent 완료: graph_id={graph_id}, simulation_id={simulation_id}")
    
    def _define_tools(self) -> Dict[str, Dict[str, Any]]:
        """에이전트가 사용할 도구 메타데이터를 정의한다."""
        return {
            "insight_forge": {
                "name": "insight_forge",
                "description": TOOL_DESC_INSIGHT_FORGE,
                "parameters": {
                    "query": "분석할 질문",
                    "report_context": "현재 보고서 섹션 맥락(선택)"
                }
            },
            "panorama_search": {
                "name": "panorama_search",
                "description": TOOL_DESC_PANORAMA_SEARCH,
                "parameters": {
                    "query": "검색 질의",
                    "include_expired": "만료/과거 사실 포함 여부(True/False)"
                }
            },
            "quick_search": {
                "name": "quick_search",
                "description": TOOL_DESC_QUICK_SEARCH,
                "parameters": {
                    "query": "검색 질의",
                    "limit": "반환 개수(선택, 기본 10)"
                }
            },
            "interview_agents": {
                "name": "interview_agents",
                "description": TOOL_DESC_INTERVIEW_AGENTS,
                "parameters": {
                    "interview_topic": "인터뷰 주제",
                    "max_agents": "인터뷰 에이전트 수(선택, 기본 5, 최대 10)"
                }
            }
        }
    
    def _execute_tool(self, tool_name: str, parameters: Dict[str, Any], report_context: str = "") -> str:
        """
        지정한 도구를 실행한다.
        
        Args:
            tool_name: 도구 이름
            parameters: 도구 파라미터
            report_context: 현재 보고서 맥락(InsightForge용)
            
        Returns:
            도구 실행 결과 텍스트
        """
        logger.info(f"도구: {tool_name}, 파라미터: {parameters}")
        
        try:
            if tool_name == "insight_forge":
                query = parameters.get("query", "")
                ctx = parameters.get("report_context", "") or report_context
                result = self.graph_tools.insight_forge(
                    graph_id=self.graph_id,
                    query=query,
                    simulation_requirement=self.simulation_requirement,
                    report_context=ctx
                )
                return result.to_text()
            
            elif tool_name == "panorama_search":
                # 전역 검색
                query = parameters.get("query", "")
                include_expired = parameters.get("include_expired", True)
                if isinstance(include_expired, str):
                    include_expired = include_expired.lower() in ['true', '1', 'yes']
                result = self.graph_tools.panorama_search(
                    graph_id=self.graph_id,
                    query=query,
                    include_expired=include_expired
                )
                return result.to_text()
            
            elif tool_name == "quick_search":
                # 빠른 검색
                query = parameters.get("query", "")
                limit = parameters.get("limit", 10)
                if isinstance(limit, str):
                    limit = int(limit)
                result = self.graph_tools.quick_search(
                    graph_id=self.graph_id,
                    query=query,
                    limit=limit
                )
                return result.to_text()
            
            elif tool_name == "interview_agents":
                # OASIS 인터뷰 API 호출
                interview_topic = parameters.get("interview_topic", parameters.get("query", ""))
                max_agents = parameters.get("max_agents", 5)
                if isinstance(max_agents, str):
                    max_agents = int(max_agents)
                max_agents = min(max_agents, 10)
                result = self.graph_tools.interview_agents(
                    simulation_id=self.simulation_id,
                    interview_requirement=interview_topic,
                    simulation_requirement=self.simulation_requirement,
                    max_agents=max_agents
                )
                return result.to_text()
            
            # ========== 호환용 별칭 도구 ==========
            
            elif tool_name == "search_graph":
                #  quick_search
                logger.info("search_graph  quick_search")
                return self._execute_tool("quick_search", parameters, report_context)
            
            elif tool_name == "get_graph_statistics":
                result = self.graph_tools.get_graph_statistics(self.graph_id)
                return json.dumps(result, ensure_ascii=False, indent=2)
            
            elif tool_name == "get_entity_summary":
                entity_name = parameters.get("entity_name", "")
                result = self.graph_tools.get_entity_summary(
                    graph_id=self.graph_id,
                    entity_name=entity_name
                )
                return json.dumps(result, ensure_ascii=False, indent=2)
            
            elif tool_name == "get_simulation_context":
                #  insight_forge, 
                logger.info("get_simulation_context  insight_forge")
                query = parameters.get("query", self.simulation_requirement)
                return self._execute_tool("insight_forge", {"query": query}, report_context)
            
            elif tool_name == "get_entities_by_type":
                entity_type = parameters.get("entity_type", "")
                nodes = self.graph_tools.get_entities_by_type(
                    graph_id=self.graph_id,
                    entity_type=entity_type
                )
                result = [n.to_dict() for n in nodes]
                return json.dumps(result, ensure_ascii=False, indent=2)
            
            else:
                return f"도구: {tool_name}.도구: insight_forge, panorama_search, quick_search"
                
        except Exception as e:
            logger.error(f"도구실패: {tool_name}, 오류: {str(e)}")
            return f"도구실패: {str(e)}"
    
    # 도구,  JSON 
    VALID_TOOL_NAMES = {"insight_forge", "panorama_search", "quick_search", "interview_agents"}

    def _parse_tool_calls(self, response: str) -> List[Dict[str, Any]]:
        """
        LLM도구호출

        ():
        1. <tool_call>{"name": "tool_name", "parameters": {...}}</tool_call>
        2.  JSON(도구 호출 JSON)
        """
        tool_calls = []

        # 1: XML()
        xml_pattern = r'<tool_call>\s*(\{.*?\})\s*</tool_call>'
        for match in re.finditer(xml_pattern, response, re.DOTALL):
            try:
                call_data = json.loads(match.group(1))
                tool_calls.append(call_data)
            except json.JSONDecodeError:
                pass

        if tool_calls:
            return tool_calls

        # 2:  - LLM  JSON( <tool_call> )
        # 1, JSON
        stripped = response.strip()
        if stripped.startswith('{') and stripped.endswith('}'):
            try:
                call_data = json.loads(stripped)
                if self._is_valid_tool_call(call_data):
                    tool_calls.append(call_data)
                    return tool_calls
            except json.JSONDecodeError:
                pass

        #  +  JSON,  JSON 
        json_pattern = r'(\{"(?:name|tool)"\s*:.*?\})\s*$'
        match = re.search(json_pattern, stripped, re.DOTALL)
        if match:
            try:
                call_data = json.loads(match.group(1))
                if self._is_valid_tool_call(call_data):
                    tool_calls.append(call_data)
            except json.JSONDecodeError:
                pass

        return tool_calls

    def _is_valid_tool_call(self, data: dict) -> bool:
        """ JSON 도구 호출"""
        #  {"name": ..., "parameters": ...}  {"tool": ..., "params": ...} 
        tool_name = data.get("name") or data.get("tool")
        if tool_name and tool_name in self.VALID_TOOL_NAMES:
            #  name / parameters
            if "tool" in data:
                data["name"] = data.pop("tool")
            if "params" in data and "parameters" not in data:
                data["parameters"] = data.pop("params")
            return True
        return False
    
    def _get_tools_description(self) -> str:
        """생성도구"""
        desc_parts = ["도구:"]
        for name, tool in self.tools.items():
            params_desc = ", ".join([f"{k}: {v}" for k, v in tool["parameters"].items()])
            desc_parts.append(f"- {name}: {tool['description']}")
            if params_desc:
                desc_parts.append(f"  파라미터: {params_desc}")
        return "\n".join(desc_parts)
    
    def plan_outline(
        self, 
        progress_callback: Optional[Callable] = None
    ) -> ReportOutline:
        """
        보고서
        
        LLM분석시뮬레이션, 보고서디렉터리
        
        Args:
            progress_callback: 진행률
            
        Returns:
            ReportOutline: 보고서
        """
        logger.info("시작보고서...")
        
        if progress_callback:
            progress_callback("planning", 0, "진행 중분석시뮬레이션...")
        
        # 시뮬레이션
        context = self.graph_tools.get_simulation_context(
            graph_id=self.graph_id,
            simulation_requirement=self.simulation_requirement
        )
        
        if progress_callback:
            progress_callback("planning", 30, "진행 중생성보고서...")
        
        system_prompt = PLAN_SYSTEM_PROMPT
        user_prompt = PLAN_USER_PROMPT_TEMPLATE.format(
            simulation_requirement=self.simulation_requirement,
            total_nodes=context.get('graph_statistics', {}).get('total_nodes', 0),
            total_edges=context.get('graph_statistics', {}).get('total_edges', 0),
            entity_types=list(context.get('graph_statistics', {}).get('entity_types', {}).keys()),
            total_entities=context.get('total_entities', 0),
            related_facts_json=json.dumps(context.get('related_facts', [])[:10], ensure_ascii=False, indent=2),
        )

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )
            
            if progress_callback:
                progress_callback("planning", 80, "진행 진행 중")
            
            # 
            sections = []
            for section_data in response.get("sections", []):
                sections.append(ReportSection(
                    title=section_data.get("title", ""),
                    content=""
                ))
            
            outline = ReportOutline(
                title=response.get("title", "시뮬레이션분석보고서"),
                summary=response.get("summary", ""),
                sections=sections
            )
            
            if progress_callback:
                progress_callback("planning", 100, "완료")
            
            logger.info(f"완료: {len(sections)}개섹션")
            return outline
            
        except Exception as e:
            logger.error(f"실패: {str(e)}")
            # 반환(3섹션, fallback)
            return ReportOutline(
                title="보고서",
                summary="시뮬레이션분석",
                sections=[
                    ReportSection(title=""),
                    ReportSection(title="분석"),
                    ReportSection(title="")
                ]
            )
    
    def _generate_section_react(
        self, 
        section: ReportSection,
        outline: ReportOutline,
        previous_sections: List[str],
        progress_callback: Optional[Callable] = None,
        section_index: int = 0
    ) -> str:
        """
        ReACT생성섹션
        
        ReACT:
        1. Thought()- 분석정보
        2. Action()- 도구 호출정보
        3. Observation()- 분석도구반환
        4. 정보
        5. Final Answer()- 생성섹션
        
        Args:
            section: 생성섹션
            outline: 
            previous_sections: 섹션()
            progress_callback: 진행률
            section_index: 섹션(로그)
            
        Returns:
            섹션(Markdown)
        """
        logger.info(f"ReACT생성섹션: {section.title}")
        
        # 섹션시작로그
        if self.report_logger:
            self.report_logger.log_section_start(section.title, section_index)
        
        system_prompt = SECTION_SYSTEM_PROMPT_TEMPLATE.format(
            report_title=outline.title,
            report_summary=outline.summary,
            simulation_requirement=self.simulation_requirement,
            section_title=section.title,
            tools_description=self._get_tools_description(),
        )

        # prompt - 완료섹션4000
        if previous_sections:
            previous_parts = []
            for sec in previous_sections:
                # 섹션4000
                truncated = sec[:4000] + "..." if len(sec) > 4000 else sec
                previous_parts.append(truncated)
            previous_content = "\n\n---\n\n".join(previous_parts)
        else:
            previous_content = "(이전에 작성된 섹션 없음)"
        
        user_prompt = SECTION_USER_PROMPT_TEMPLATE.format(
            previous_content=previous_content,
            section_title=section.title,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        # ReACT
        tool_calls_count = 0
        max_iterations = 5  # 
        min_tool_calls = 3  # 도구 호출
        conflict_retries = 0  # 도구 호출Final Answer
        used_tools = set()  # 도구 호출
        all_tools = {"insight_forge", "panorama_search", "quick_search", "interview_agents"}

        # 보고서, InsightForge질문생성
        report_context = f"섹션: {section.title}\n시뮬레이션: {self.simulation_requirement}"
        
        for iteration in range(max_iterations):
            if progress_callback:
                progress_callback(
                    "generating", 
                    int((iteration / max_iterations) * 100),
                    f"섹션 생성 진행 중 (도구 호출 {tool_calls_count}/{self.MAX_TOOL_CALLS_PER_SECTION})"
                )
            
            # 호출LLM
            response = self.llm.chat(
                messages=messages,
                temperature=0.5,
                max_tokens=4096
            )

            #  LLM 반환 None(API )
            if response is None:
                logger.warning(f"섹션 {section.title}  {iteration + 1}회: LLM 반환 None")
                # , 
                if iteration < max_iterations - 1:
                    messages.append({"role": "assistant", "content": "(응답 생성 실패) 다시 시도합니다."})
                    messages.append({"role": "user", "content": "이전 지침을 유지한 채 섹션을 다시 작성해 주세요."})
                    continue
                # 반환 None, 
                break

            logger.debug(f"LLM: {response[:200]}...")

            # , 
            tool_calls = self._parse_tool_calls(response)
            has_tool_calls = bool(tool_calls)
            has_final_answer = "Final Answer:" in response

            # ── :LLM 도구 호출 Final Answer ──
            if has_tool_calls and has_final_answer:
                conflict_retries += 1
                logger.warning(
                    f"섹션 {section.title}  {iteration+1} : "
                    f"LLM 도구 호출 Final Answer( {conflict_retries}회)"
                )

                if conflict_retries <= 2:
                    # :,  LLM 
                    messages.append({"role": "assistant", "content": response})
                    messages.append({
                        "role": "user",
                        "content": (
                            "[오류]진행 중도구 호출 Final Answer, .\n"
                            ":\n"
                            "- 도구 호출( <tool_call> ,  Final Answer)\n"
                            "- ( 'Final Answer:' ,  <tool_call>)\n"
                            ", 진행 중."
                        ),
                    })
                    continue
                else:
                    # :, 도구 호출, 
                    logger.warning(
                        f"섹션 {section.title}:  {conflict_retries}회, "
                        "도구 호출"
                    )
                    first_tool_end = response.find('</tool_call>')
                    if first_tool_end != -1:
                        response = response[:first_tool_end + len('</tool_call>')]
                        tool_calls = self._parse_tool_calls(response)
                        has_tool_calls = bool(tool_calls)
                    has_final_answer = False
                    conflict_retries = 0

            #  LLM 로그
            if self.report_logger:
                self.report_logger.log_llm_response(
                    section_title=section.title,
                    section_index=section_index,
                    response=response,
                    iteration=iteration + 1,
                    has_tool_calls=has_tool_calls,
                    has_final_answer=has_final_answer
                )

            # ── 1:LLM  Final Answer ──
            if has_final_answer:
                # 도구 호출, 도구
                if tool_calls_count < min_tool_calls:
                    messages.append({"role": "assistant", "content": response})
                    unused_tools = all_tools - used_tools
                    unused_hint = f"(도구, : {', '.join(unused_tools)})" if unused_tools else ""
                    messages.append({
                        "role": "user",
                        "content": REACT_INSUFFICIENT_TOOLS_MSG.format(
                            tool_calls_count=tool_calls_count,
                            min_tool_calls=min_tool_calls,
                            unused_hint=unused_hint,
                        ),
                    })
                    continue

                # 
                final_answer = response.split("Final Answer:")[-1].strip()
                logger.info(f"섹션 {section.title} 생성완료(도구 호출: {tool_calls_count})")

                if self.report_logger:
                    self.report_logger.log_section_content(
                        section_title=section.title,
                        section_index=section_index,
                        content=final_answer,
                        tool_calls_count=tool_calls_count
                    )
                return final_answer

            # ── 2:LLM 도구 호출 ──
            if has_tool_calls:
                # 도구 → ,  Final Answer
                if tool_calls_count >= self.MAX_TOOL_CALLS_PER_SECTION:
                    messages.append({"role": "assistant", "content": response})
                    messages.append({
                        "role": "user",
                        "content": REACT_TOOL_LIMIT_MSG.format(
                            tool_calls_count=tool_calls_count,
                            max_tool_calls=self.MAX_TOOL_CALLS_PER_SECTION,
                        ),
                    })
                    continue

                # 도구 호출
                call = tool_calls[0]
                if len(tool_calls) > 1:
                    logger.info(f"LLM 호출 {len(tool_calls)}개도구, : {call['name']}")

                if self.report_logger:
                    self.report_logger.log_tool_call(
                        section_title=section.title,
                        section_index=section_index,
                        tool_name=call["name"],
                        parameters=call.get("parameters", {}),
                        iteration=iteration + 1
                    )

                result = self._execute_tool(
                    call["name"],
                    call.get("parameters", {}),
                    report_context=report_context
                )

                if self.report_logger:
                    self.report_logger.log_tool_result(
                        section_title=section.title,
                        section_index=section_index,
                        tool_name=call["name"],
                        result=result,
                        iteration=iteration + 1
                    )

                tool_calls_count += 1
                used_tools.add(call['name'])

                # 도구
                unused_tools = all_tools - used_tools
                unused_hint = ""
                if unused_tools and tool_calls_count < self.MAX_TOOL_CALLS_PER_SECTION:
                    unused_hint = REACT_UNUSED_TOOLS_HINT.format(unused_list=", ".join(unused_tools))

                messages.append({"role": "assistant", "content": response})
                messages.append({
                    "role": "user",
                    "content": REACT_OBSERVATION_TEMPLATE.format(
                        tool_name=call["name"],
                        result=result,
                        tool_calls_count=tool_calls_count,
                        max_tool_calls=self.MAX_TOOL_CALLS_PER_SECTION,
                        used_tools_str=", ".join(used_tools),
                        unused_hint=unused_hint,
                    ),
                })
                continue

            # ── 3:도구 호출,  Final Answer ──
            messages.append({"role": "assistant", "content": response})

            if tool_calls_count < min_tool_calls:
                # 도구 호출, 도구
                unused_tools = all_tools - used_tools
                unused_hint = f"(도구, : {', '.join(unused_tools)})" if unused_tools else ""

                messages.append({
                    "role": "user",
                    "content": REACT_INSUFFICIENT_TOOLS_MSG_ALT.format(
                        tool_calls_count=tool_calls_count,
                        min_tool_calls=min_tool_calls,
                        unused_hint=unused_hint,
                    ),
                })
                continue

            # 도구 호출, LLM  "Final Answer:" 
            # , 
            logger.info(f"섹션 {section.title}  'Final Answer:' , LLM(도구 호출: {tool_calls_count})")
            final_answer = response.strip()

            if self.report_logger:
                self.report_logger.log_section_content(
                    section_title=section.title,
                    section_index=section_index,
                    content=final_answer,
                    tool_calls_count=tool_calls_count
                )
            return final_answer
        
        # , 생성
        logger.warning(f"섹션 {section.title} , 생성")
        messages.append({"role": "user", "content": REACT_FORCE_FINAL_MSG})
        
        response = self.llm.chat(
            messages=messages,
            temperature=0.5,
            max_tokens=4096
        )

        #  LLM 반환 None
        if response is None:
            logger.error(f"섹션 {section.title}  LLM 반환 None, 오류")
            final_answer = f"(섹션생성 실패:LLM 반환, )"
        elif "Final Answer:" in response:
            final_answer = response.split("Final Answer:")[-1].strip()
        else:
            final_answer = response
        
        # 섹션생성완료로그
        if self.report_logger:
            self.report_logger.log_section_content(
                section_title=section.title,
                section_index=section_index,
                content=final_answer,
                tool_calls_count=tool_calls_count
            )
        
        return final_answer
    
    def generate_report(
        self, 
        progress_callback: Optional[Callable[[str, int, str], None]] = None,
        report_id: Optional[str] = None
    ) -> Report:
        """
        생성보고서(섹션)
        
        섹션생성완료저장파일, 보고서완료.
        파일:
        reports/{report_id}/
            meta.json       - 보고서정보
            outline.json    - 보고서
            progress.json   - 생성진행률
            section_01.md   - 1섹션
            section_02.md   - 2섹션
            ...
            full_report.md  - 보고서
        
        Args:
            progress_callback: 진행률 (stage, progress, message)
            report_id: 보고서ID(선택, 생성)
            
        Returns:
            Report: 보고서
        """
        import uuid
        
        #  report_id, 생성
        if not report_id:
            report_id = f"report_{uuid.uuid4().hex[:12]}"
        start_time = datetime.now()
        
        report = Report(
            report_id=report_id,
            simulation_id=self.simulation_id,
            graph_id=self.graph_id,
            simulation_requirement=self.simulation_requirement,
            status=ReportStatus.PENDING,
            created_at=datetime.now().isoformat()
        )
        
        # 완료섹션목록(진행률)
        completed_section_titles = []
        
        try:
            # :보고서파일저장상태
            ReportManager._ensure_report_folder(report_id)
            
            # 로그(로그 agent_log.jsonl)
            self.report_logger = ReportLogger(report_id)
            self.report_logger.log_start(
                simulation_id=self.simulation_id,
                graph_id=self.graph_id,
                simulation_requirement=self.simulation_requirement
            )
            
            # 콘솔로그(console_log.txt)
            self.console_logger = ReportConsoleLogger(report_id)
            
            ReportManager.update_progress(
                report_id, "pending", 0, "보고서...",
                completed_sections=[]
            )
            ReportManager.save_report(report)
            
            # 1: 
            report.status = ReportStatus.PLANNING
            ReportManager.update_progress(
                report_id, "planning", 5, "시작보고서...",
                completed_sections=[]
            )
            
            # 시작로그
            self.report_logger.log_planning_start()
            
            if progress_callback:
                progress_callback("planning", 0, "시작보고서...")
            
            outline = self.plan_outline(
                progress_callback=lambda stage, prog, msg: 
                    progress_callback(stage, prog // 5, msg) if progress_callback else None
            )
            report.outline = outline
            
            # 완료로그
            self.report_logger.log_planning_complete(outline.to_dict())
            
            # 저장파일
            ReportManager.save_outline(report_id, outline)
            ReportManager.update_progress(
                report_id, "planning", 15, f"완료, {len(outline.sections)}섹션",
                completed_sections=[]
            )
            ReportManager.save_report(report)
            
            logger.info(f"저장파일: {report_id}/outline.json")
            
            # 2: 섹션생성(섹션저장)
            report.status = ReportStatus.GENERATING
            
            total_sections = len(outline.sections)
            generated_sections = []  # 저장
            
            for i, section in enumerate(outline.sections):
                section_num = i + 1
                base_progress = 20 + int((i / total_sections) * 70)
                
                # 진행률
                ReportManager.update_progress(
                    report_id, "generating", base_progress,
                    f"진행 중생성섹션: {section.title} ({section_num}/{total_sections})",
                    current_section=section.title,
                    completed_sections=completed_section_titles
                )
                
                if progress_callback:
                    progress_callback(
                        "generating", 
                        base_progress, 
                        f"진행 중생성섹션: {section.title} ({section_num}/{total_sections})"
                    )
                
                # 생성섹션
                section_content = self._generate_section_react(
                    section=section,
                    outline=outline,
                    previous_sections=generated_sections,
                    progress_callback=lambda stage, prog, msg:
                        progress_callback(
                            stage, 
                            base_progress + int(prog * 0.7 / total_sections),
                            msg
                        ) if progress_callback else None,
                    section_index=section_num
                )
                
                section.content = section_content
                generated_sections.append(f"## {section.title}\n\n{section_content}")

                # 저장섹션
                ReportManager.save_section(report_id, section_num, section)
                completed_section_titles.append(section.title)

                # 섹션완료로그
                full_section_content = f"## {section.title}\n\n{section_content}"

                if self.report_logger:
                    self.report_logger.log_section_full_complete(
                        section_title=section.title,
                        section_index=section_num,
                        full_content=full_section_content.strip()
                    )

                logger.info(f"섹션저장: {report_id}/section_{section_num:02d}.md")
                
                # 진행률
                ReportManager.update_progress(
                    report_id, "generating", 
                    base_progress + int(70 / total_sections),
                    f"섹션 {section.title} 완료",
                    current_section=None,
                    completed_sections=completed_section_titles
                )
            
            # 3: 보고서
            if progress_callback:
                progress_callback("generating", 95, "진행 중보고서...")
            
            ReportManager.update_progress(
                report_id, "generating", 95, "진행 중보고서...",
                completed_sections=completed_section_titles
            )
            
            # ReportManager보고서
            report.markdown_content = ReportManager.assemble_full_report(report_id, outline)
            report.status = ReportStatus.COMPLETED
            report.completed_at = datetime.now().isoformat()
            
            # 
            total_time_seconds = (datetime.now() - start_time).total_seconds()
            
            # 보고서완료로그
            if self.report_logger:
                self.report_logger.log_report_complete(
                    total_sections=total_sections,
                    total_time_seconds=total_time_seconds
                )
            
            # 저장보고서
            ReportManager.save_report(report)
            ReportManager.update_progress(
                report_id, "completed", 100, "보고서 생성완료",
                completed_sections=completed_section_titles
            )
            
            if progress_callback:
                progress_callback("completed", 100, "보고서 생성완료")
            
            logger.info(f"보고서 생성완료: {report_id}")
            
            # 콘솔로그
            if self.console_logger:
                self.console_logger.close()
                self.console_logger = None
            
            return report
            
        except Exception as e:
            logger.error(f"보고서 생성 실패: {str(e)}")
            report.status = ReportStatus.FAILED
            report.error = str(e)
            
            # 오류로그
            if self.report_logger:
                self.report_logger.log_error(str(e), "failed")
            
            # 저장실패상태
            try:
                ReportManager.save_report(report)
                ReportManager.update_progress(
                    report_id, "failed", -1, f"보고서 생성 실패: {str(e)}",
                    completed_sections=completed_section_titles
                )
            except Exception:
                pass  # 저장실패오류
            
            # 콘솔로그
            if self.console_logger:
                self.console_logger.close()
                self.console_logger = None
            
            return report
    
    def chat(
        self, 
        message: str,
        chat_history: List[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Report Agent
        
        에이전트도구 호출질문
        
        Args:
            message: 
            chat_history: 과거
            
        Returns:
            {
                "response": "Agent",
                "tool_calls": [도구 호출목록],
                "sources": [정보출처]
            }
        """
        logger.info(f"Report Agent: {message[:50]}...")
        
        chat_history = chat_history or []
        
        # 생성보고서
        report_content = ""
        try:
            report = ReportManager.get_report_by_simulation(self.simulation_id)
            if report and report.markdown_content:
                # 보고서, 
                report_content = report.markdown_content[:15000]
                if len(report.markdown_content) > 15000:
                    report_content += "\n\n... [보고서] ..."
        except Exception as e:
            logger.warning(f"보고서실패: {e}")
        
        system_prompt = CHAT_SYSTEM_PROMPT_TEMPLATE.format(
            simulation_requirement=self.simulation_requirement,
            report_content=report_content if report_content else "(보고서)",
            tools_description=self._get_tools_description(),
        )

        # 
        messages = [{"role": "system", "content": system_prompt}]
        
        # 과거
        for h in chat_history[-10:]:  # 과거
            messages.append(h)
        
        # 
        messages.append({
            "role": "user", 
            "content": message
        })
        
        # ReACT()
        tool_calls_made = []
        max_iterations = 2  # 
        
        for iteration in range(max_iterations):
            response = self.llm.chat(
                messages=messages,
                temperature=0.5
            )
            
            # 도구 호출
            tool_calls = self._parse_tool_calls(response)
            
            if not tool_calls:
                # 도구 호출, 반환
                clean_response = re.sub(r'<tool_call>.*?</tool_call>', '', response, flags=re.DOTALL)
                clean_response = re.sub(r'\[TOOL_CALL\].*?\)', '', clean_response)
                
                return {
                    "response": clean_response.strip(),
                    "tool_calls": tool_calls_made,
                    "sources": [tc.get("parameters", {}).get("query", "") for tc in tool_calls_made]
                }
            
            # 도구 호출()
            tool_results = []
            for call in tool_calls[:1]:  # 1도구 호출
                if len(tool_calls_made) >= self.MAX_TOOL_CALLS_PER_CHAT:
                    break
                result = self._execute_tool(call["name"], call.get("parameters", {}))
                tool_results.append({
                    "tool": call["name"],
                    "result": result[:1500]  # 
                })
                tool_calls_made.append(call)
            
            # 
            messages.append({"role": "assistant", "content": response})
            observation = "\n".join([f"[{r['tool']}]\n{r['result']}" for r in tool_results])
            messages.append({
                "role": "user",
                "content": observation + CHAT_OBSERVATION_SUFFIX
            })
        
        # , 
        final_response = self.llm.chat(
            messages=messages,
            temperature=0.5
        )
        
        # 
        clean_response = re.sub(r'<tool_call>.*?</tool_call>', '', final_response, flags=re.DOTALL)
        clean_response = re.sub(r'\[TOOL_CALL\].*?\)', '', clean_response)
        
        return {
            "response": clean_response.strip(),
            "tool_calls": tool_calls_made,
            "sources": [tc.get("parameters", {}).get("query", "") for tc in tool_calls_made]
        }


class ReportManager:
    """
    보고서
    
    보고서
    
    파일(섹션):
    reports/
      {report_id}/
        meta.json          - 보고서정보상태
        outline.json       - 보고서
        progress.json      - 생성진행률
        section_01.md      - 1섹션
        section_02.md      - 2섹션
        ...
        full_report.md     - 보고서
    """
    
    # 보고서디렉터리
    REPORTS_DIR = os.path.join(Config.UPLOAD_FOLDER, 'reports')
    
    @classmethod
    def _ensure_reports_dir(cls):
        """보고서디렉터리"""
        os.makedirs(cls.REPORTS_DIR, exist_ok=True)
    
    @classmethod
    def _get_report_folder(cls, report_id: str) -> str:
        """보고서파일"""
        return os.path.join(cls.REPORTS_DIR, report_id)
    
    @classmethod
    def _ensure_report_folder(cls, report_id: str) -> str:
        """보고서파일반환"""
        folder = cls._get_report_folder(report_id)
        os.makedirs(folder, exist_ok=True)
        return folder
    
    @classmethod
    def _get_report_path(cls, report_id: str) -> str:
        """보고서정보파일"""
        return os.path.join(cls._get_report_folder(report_id), "meta.json")
    
    @classmethod
    def _get_report_markdown_path(cls, report_id: str) -> str:
        """보고서Markdown파일"""
        return os.path.join(cls._get_report_folder(report_id), "full_report.md")
    
    @classmethod
    def _get_outline_path(cls, report_id: str) -> str:
        """파일"""
        return os.path.join(cls._get_report_folder(report_id), "outline.json")
    
    @classmethod
    def _get_progress_path(cls, report_id: str) -> str:
        """진행률파일"""
        return os.path.join(cls._get_report_folder(report_id), "progress.json")
    
    @classmethod
    def _get_section_path(cls, report_id: str, section_index: int) -> str:
        """섹션Markdown파일"""
        return os.path.join(cls._get_report_folder(report_id), f"section_{section_index:02d}.md")
    
    @classmethod
    def _get_agent_log_path(cls, report_id: str) -> str:
        """ Agent 로그파일"""
        return os.path.join(cls._get_report_folder(report_id), "agent_log.jsonl")
    
    @classmethod
    def _get_console_log_path(cls, report_id: str) -> str:
        """콘솔로그파일"""
        return os.path.join(cls._get_report_folder(report_id), "console_log.txt")
    
    @classmethod
    def get_console_log(cls, report_id: str, from_line: int = 0) -> Dict[str, Any]:
        """
        콘솔로그
        
        보고서 생성진행 중로그(INFO, WARNING), 
         agent_log.jsonl 로그.
        
        Args:
            report_id: 보고서ID
            from_line: 시작읽기(, 0 시작)
            
        Returns:
            {
                "logs": [로그목록],
                "total_lines": ,
                "from_line": ,
                "has_more": 로그
            }
        """
        log_path = cls._get_console_log_path(report_id)
        
        if not os.path.exists(log_path):
            return {
                "logs": [],
                "total_lines": 0,
                "from_line": 0,
                "has_more": False
            }
        
        logs = []
        total_lines = 0
        
        with open(log_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                total_lines = i + 1
                if i >= from_line:
                    # 로그, 
                    logs.append(line.rstrip('\n\r'))
        
        return {
            "logs": logs,
            "total_lines": total_lines,
            "from_line": from_line,
            "has_more": False  # 읽기
        }
    
    @classmethod
    def get_console_log_stream(cls, report_id: str) -> List[str]:
        """
        콘솔로그()
        
        Args:
            report_id: 보고서ID
            
        Returns:
            로그목록
        """
        result = cls.get_console_log(report_id, from_line=0)
        return result["logs"]
    
    @classmethod
    def get_agent_log(cls, report_id: str, from_line: int = 0) -> Dict[str, Any]:
        """
         Agent 로그
        
        Args:
            report_id: 보고서ID
            from_line: 시작읽기(, 0 시작)
            
        Returns:
            {
                "logs": [로그목록],
                "total_lines": ,
                "from_line": ,
                "has_more": 로그
            }
        """
        log_path = cls._get_agent_log_path(report_id)
        
        if not os.path.exists(log_path):
            return {
                "logs": [],
                "total_lines": 0,
                "from_line": 0,
                "has_more": False
            }
        
        logs = []
        total_lines = 0
        
        with open(log_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                total_lines = i + 1
                if i >= from_line:
                    try:
                        log_entry = json.loads(line.strip())
                        logs.append(log_entry)
                    except json.JSONDecodeError:
                        # 실패
                        continue
        
        return {
            "logs": logs,
            "total_lines": total_lines,
            "from_line": from_line,
            "has_more": False  # 읽기
        }
    
    @classmethod
    def get_agent_log_stream(cls, report_id: str) -> List[Dict[str, Any]]:
        """
         Agent 로그()
        
        Args:
            report_id: 보고서ID
            
        Returns:
            로그목록
        """
        result = cls.get_agent_log(report_id, from_line=0)
        return result["logs"]
    
    @classmethod
    def save_outline(cls, report_id: str, outline: ReportOutline) -> None:
        """
        저장보고서
        
        완료호출
        """
        cls._ensure_report_folder(report_id)
        
        with open(cls._get_outline_path(report_id), 'w', encoding='utf-8') as f:
            json.dump(outline.to_dict(), f, ensure_ascii=False, indent=2)
        
        logger.info(f"저장: {report_id}")
    
    @classmethod
    def save_section(
        cls,
        report_id: str,
        section_index: int,
        section: ReportSection
    ) -> str:
        """
        저장섹션

        섹션생성완료호출, 섹션

        Args:
            report_id: 보고서ID
            section_index: 섹션(1시작)
            section: 섹션

        Returns:
            저장파일
        """
        cls._ensure_report_folder(report_id)

        # 섹션Markdown - 
        cleaned_content = cls._clean_section_content(section.content, section.title)
        md_content = f"## {section.title}\n\n"
        if cleaned_content:
            md_content += f"{cleaned_content}\n\n"

        # 저장파일
        file_suffix = f"section_{section_index:02d}.md"
        file_path = os.path.join(cls._get_report_folder(report_id), file_suffix)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(md_content)

        logger.info(f"섹션저장: {report_id}/{file_suffix}")
        return file_path
    
    @classmethod
    def _clean_section_content(cls, content: str, section_title: str) -> str:
        """
        섹션
        
        1. 섹션Markdown
        2.  ### 
        
        Args:
            content: 
            section_title: 섹션
            
        Returns:
            
        """
        import re
        
        if not content:
            return content
        
        content = content.strip()
        lines = content.split('\n')
        cleaned_lines = []
        skip_next_empty = False
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            
            # Markdown
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', stripped)
            
            if heading_match:
                level = len(heading_match.group(1))
                title_text = heading_match.group(2).strip()
                
                # 섹션(5)
                if i < 5:
                    if title_text == section_title or title_text.replace(' ', '') == section_title.replace(' ', ''):
                        skip_next_empty = True
                        continue
                
                # (#, ##, ###, ####)
                # 섹션, 진행 중
                cleaned_lines.append(f"**{title_text}**")
                cleaned_lines.append("")  # 
                continue
            
            # , 현재, 
            if skip_next_empty and stripped == '':
                skip_next_empty = False
                continue
            
            skip_next_empty = False
            cleaned_lines.append(line)
        
        # 
        while cleaned_lines and cleaned_lines[0].strip() == '':
            cleaned_lines.pop(0)
        
        # 
        while cleaned_lines and cleaned_lines[0].strip() in ['---', '***', '___']:
            cleaned_lines.pop(0)
            # 
            while cleaned_lines and cleaned_lines[0].strip() == '':
                cleaned_lines.pop(0)
        
        return '\n'.join(cleaned_lines)
    
    @classmethod
    def update_progress(
        cls, 
        report_id: str, 
        status: str, 
        progress: int, 
        message: str,
        current_section: str = None,
        completed_sections: List[str] = None
    ) -> None:
        """
        보고서 생성진행률
        
        읽기progress.json진행률
        """
        cls._ensure_report_folder(report_id)
        
        progress_data = {
            "status": status,
            "progress": progress,
            "message": message,
            "current_section": current_section,
            "completed_sections": completed_sections or [],
            "updated_at": datetime.now().isoformat()
        }
        
        with open(cls._get_progress_path(report_id), 'w', encoding='utf-8') as f:
            json.dump(progress_data, f, ensure_ascii=False, indent=2)
    
    @classmethod
    def get_progress(cls, report_id: str) -> Optional[Dict[str, Any]]:
        """보고서 생성진행률"""
        path = cls._get_progress_path(report_id)
        
        if not os.path.exists(path):
            return None
        
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    @classmethod
    def get_generated_sections(cls, report_id: str) -> List[Dict[str, Any]]:
        """
        생성섹션목록
        
        반환저장섹션파일정보
        """
        folder = cls._get_report_folder(report_id)
        
        if not os.path.exists(folder):
            return []
        
        sections = []
        for filename in sorted(os.listdir(folder)):
            if filename.startswith('section_') and filename.endswith('.md'):
                file_path = os.path.join(folder, filename)
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # 파일섹션
                parts = filename.replace('.md', '').split('_')
                section_index = int(parts[1])

                sections.append({
                    "filename": filename,
                    "section_index": section_index,
                    "content": content
                })

        return sections
    
    @classmethod
    def assemble_full_report(cls, report_id: str, outline: ReportOutline) -> str:
        """
        보고서
        
        저장섹션파일보고서, 
        """
        folder = cls._get_report_folder(report_id)
        
        # 보고서
        md_content = f"# {outline.title}\n\n"
        md_content += f"> {outline.summary}\n\n"
        md_content += f"---\n\n"
        
        # 읽기섹션파일
        sections = cls.get_generated_sections(report_id)
        for section_info in sections:
            md_content += section_info["content"]
        
        # :보고서질문
        md_content = cls._post_process_report(md_content, outline)
        
        # 저장보고서
        full_path = cls._get_report_markdown_path(report_id)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(md_content)
        
        logger.info(f"보고서: {report_id}")
        return md_content
    
    @classmethod
    def _post_process_report(cls, content: str, outline: ReportOutline) -> str:
        """
        보고서
        
        1. 
        2. 보고서(#)섹션(##), (###, ####)
        3. 
        
        Args:
            content: 보고서
            outline: 보고서
            
        Returns:
            
        """
        import re
        
        lines = content.split('\n')
        processed_lines = []
        prev_was_heading = False
        
        # 진행 중섹션
        section_titles = set()
        for section in outline.sections:
            section_titles.add(section.title)
        
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            
            # 
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', stripped)
            
            if heading_match:
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()
                
                # (5)
                is_duplicate = False
                for j in range(max(0, len(processed_lines) - 5), len(processed_lines)):
                    prev_line = processed_lines[j].strip()
                    prev_match = re.match(r'^(#{1,6})\s+(.+)$', prev_line)
                    if prev_match:
                        prev_title = prev_match.group(2).strip()
                        if prev_title == title:
                            is_duplicate = True
                            break
                
                if is_duplicate:
                    # 
                    i += 1
                    while i < len(lines) and lines[i].strip() == '':
                        i += 1
                    continue
                
                # :
                # - # (level=1) 보고서
                # - ## (level=2) 섹션
                # - ###  (level>=3) 
                
                if level == 1:
                    if title == outline.title:
                        # 보고서
                        processed_lines.append(line)
                        prev_was_heading = True
                    elif title in section_titles:
                        # 섹션오류#, ##
                        processed_lines.append(f"## {title}")
                        prev_was_heading = True
                    else:
                        # 
                        processed_lines.append(f"**{title}**")
                        processed_lines.append("")
                        prev_was_heading = False
                elif level == 2:
                    if title in section_titles or title == outline.title:
                        # 섹션
                        processed_lines.append(line)
                        prev_was_heading = True
                    else:
                        # 섹션
                        processed_lines.append(f"**{title}**")
                        processed_lines.append("")
                        prev_was_heading = False
                else:
                    # ### 
                    processed_lines.append(f"**{title}**")
                    processed_lines.append("")
                    prev_was_heading = False
                
                i += 1
                continue
            
            elif stripped == '---' and prev_was_heading:
                # 
                i += 1
                continue
            
            elif stripped == '' and prev_was_heading:
                # 
                if processed_lines and processed_lines[-1].strip() != '':
                    processed_lines.append(line)
                prev_was_heading = False
            
            else:
                processed_lines.append(line)
                prev_was_heading = False
            
            i += 1
        
        # (2)
        result_lines = []
        empty_count = 0
        for line in processed_lines:
            if line.strip() == '':
                empty_count += 1
                if empty_count <= 2:
                    result_lines.append(line)
            else:
                empty_count = 0
                result_lines.append(line)
        
        return '\n'.join(result_lines)
    
    @classmethod
    def save_report(cls, report: Report) -> None:
        """저장보고서정보보고서"""
        cls._ensure_report_folder(report.report_id)
        
        # 저장정보JSON
        with open(cls._get_report_path(report.report_id), 'w', encoding='utf-8') as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
        
        # 저장
        if report.outline:
            cls.save_outline(report.report_id, report.outline)
        
        # 저장Markdown보고서
        if report.markdown_content:
            with open(cls._get_report_markdown_path(report.report_id), 'w', encoding='utf-8') as f:
                f.write(report.markdown_content)
        
        logger.info(f"보고서저장: {report.report_id}")
    
    @classmethod
    def get_report(cls, report_id: str) -> Optional[Report]:
        """보고서"""
        path = cls._get_report_path(report_id)
        
        if not os.path.exists(path):
            # :reports디렉터리파일
            old_path = os.path.join(cls.REPORTS_DIR, f"{report_id}.json")
            if os.path.exists(old_path):
                path = old_path
            else:
                return None
        
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Report
        outline = None
        if data.get('outline'):
            outline_data = data['outline']
            sections = []
            for s in outline_data.get('sections', []):
                sections.append(ReportSection(
                    title=s['title'],
                    content=s.get('content', '')
                ))
            outline = ReportOutline(
                title=outline_data['title'],
                summary=outline_data['summary'],
                sections=sections
            )
        
        # markdown_content, full_report.md읽기
        markdown_content = data.get('markdown_content', '')
        if not markdown_content:
            full_report_path = cls._get_report_markdown_path(report_id)
            if os.path.exists(full_report_path):
                with open(full_report_path, 'r', encoding='utf-8') as f:
                    markdown_content = f.read()
        
        return Report(
            report_id=data['report_id'],
            simulation_id=data['simulation_id'],
            graph_id=data['graph_id'],
            simulation_requirement=data['simulation_requirement'],
            status=ReportStatus(data['status']),
            outline=outline,
            markdown_content=markdown_content,
            created_at=data.get('created_at', ''),
            completed_at=data.get('completed_at', ''),
            error=data.get('error')
        )
    
    @classmethod
    def get_report_by_simulation(cls, simulation_id: str) -> Optional[Report]:
        """시뮬레이션ID보고서"""
        cls._ensure_reports_dir()
        
        for item in os.listdir(cls.REPORTS_DIR):
            item_path = os.path.join(cls.REPORTS_DIR, item)
            # :파일
            if os.path.isdir(item_path):
                report = cls.get_report(item)
                if report and report.simulation_id == simulation_id:
                    return report
            # :JSON파일
            elif item.endswith('.json'):
                report_id = item[:-5]
                report = cls.get_report(report_id)
                if report and report.simulation_id == simulation_id:
                    return report
        
        return None
    
    @classmethod
    def list_reports(cls, simulation_id: Optional[str] = None, limit: int = 50) -> List[Report]:
        """보고서"""
        cls._ensure_reports_dir()
        
        reports = []
        for item in os.listdir(cls.REPORTS_DIR):
            item_path = os.path.join(cls.REPORTS_DIR, item)
            # :파일
            if os.path.isdir(item_path):
                report = cls.get_report(item)
                if report:
                    if simulation_id is None or report.simulation_id == simulation_id:
                        reports.append(report)
            # :JSON파일
            elif item.endswith('.json'):
                report_id = item[:-5]
                report = cls.get_report(report_id)
                if report:
                    if simulation_id is None or report.simulation_id == simulation_id:
                        reports.append(report)
        
        # 
        reports.sort(key=lambda r: r.created_at, reverse=True)
        
        return reports[:limit]
    
    @classmethod
    def delete_report(cls, report_id: str) -> bool:
        """삭제보고서(파일)"""
        import shutil
        
        folder_path = cls._get_report_folder(report_id)
        
        # :삭제파일
        if os.path.exists(folder_path) and os.path.isdir(folder_path):
            shutil.rmtree(folder_path)
            logger.info(f"보고서파일삭제: {report_id}")
            return True
        
        # :삭제파일
        deleted = False
        old_json_path = os.path.join(cls.REPORTS_DIR, f"{report_id}.json")
        old_md_path = os.path.join(cls.REPORTS_DIR, f"{report_id}.md")
        
        if os.path.exists(old_json_path):
            os.remove(old_json_path)
            deleted = True
        if os.path.exists(old_md_path):
            os.remove(old_md_path)
            deleted = True
        
        return deleted
