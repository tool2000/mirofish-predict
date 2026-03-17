"""
온톨로지 생성 서비스.
API 1: 문서 내용을 분석해 사회 시뮬레이션에 맞는 엔터티/관계 타입을 생성한다.
"""

import json
from typing import Dict, Any, List, Optional
from ..utils.llm_client import LLMClient


# 온톨로지 생성을 위한 시스템 프롬프트
ONTOLOGY_SYSTEM_PROMPT = """너는 지식 그래프 온톨로지 설계 전문가다.
주어진 문서 내용과 시뮬레이션 요구사항을 바탕으로 **소셜 미디어 여론 시뮬레이션**에 맞는
엔터티 타입과 관계 타입을 설계하라.

중요:
- 반드시 **유효한 JSON만** 출력한다.
- JSON 외 텍스트는 절대 출력하지 않는다.

## 작업 배경

우리는 소셜 미디어 여론 시뮬레이션 시스템을 구축한다.
이 시스템에서 엔터티는 실제로 발화/상호작용/정보 확산이 가능한 주체여야 한다.

엔터티 예시(허용):
- 개인(공인, 당사자, 전문가, 일반 사용자 등)
- 기업/기관/단체(공식 계정 포함)
- 정부 부처/규제기관
- 언론사/플랫폼
- 특정 집단 대표(팬덤, 동문회, 시민단체 등)

엔터티 예시(금지):
- 추상 개념(여론, 감정, 추세 등)
- 주제/이슈(교육 개혁, 학술 윤리 등)
- 태도 자체(찬성 진영, 반대 진영 등)

## 출력 형식

아래 구조를 가진 JSON으로 출력:

```json
{
  "entity_types": [
    {
      "name": "EntityTypeName (영문 PascalCase)",
      "description": "영문 설명(100자 이내)",
      "attributes": [
        {
          "name": "attribute_name (영문 snake_case)",
          "type": "text",
          "description": "속성 설명"
        }
      ],
      "examples": ["example1", "example2"]
    }
  ],
  "edge_types": [
    {
      "name": "RELATION_NAME (영문 UPPER_SNAKE_CASE)",
      "description": "영문 설명(100자 이내)",
      "source_targets": [
        {"source": "SourceEntityType", "target": "TargetEntityType"}
      ],
      "attributes": []
    }
  ],
  "analysis_summary": "문서 핵심 분석 요약"
}
```

## 설계 규칙 (반드시 준수)

1) 엔터티 타입
- 정확히 **10개**를 출력한다.
- 마지막 2개는 반드시 fallback 타입:
  - `Person`
  - `Organization`
- 앞 8개는 문서 맥락 기반의 구체 타입으로 설계한다.

2) 관계 타입
- 6~10개로 설계한다.
- 실제 소셜 상호작용(영향, 언급, 반응, 협업, 대립 등)을 반영한다.
- `source_targets`가 정의된 엔터티 타입들을 충분히 포괄해야 한다.

3) 속성 타입
- 엔터티 타입당 1~3개 핵심 속성만 정의한다.
- 예약어는 속성명으로 사용 금지:
  `name`, `uuid`, `group_id`, `created_at`, `summary`
- 권장 예시:
  `full_name`, `title`, `role`, `position`, `location`, `description`
"""


class OntologyGenerator:
    """
    온톨로지 생성기.
    문서 내용을 분석해 엔터티/관계 타입 정의를 생성한다.
    """
    
    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or LLMClient()
    
    def generate(
        self,
        document_texts: List[str],
        simulation_requirement: str,
        additional_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        온톨로지 정의를 생성한다.

        Args:
            document_texts: 문서 텍스트 목록
            simulation_requirement: 시뮬레이션 요구사항
            additional_context: 추가 컨텍스트

        Returns:
            온톨로지 정의(`entity_types`, `edge_types` 등)
        """
        # 사용자 메시지 구성
        user_message = self._build_user_message(
            document_texts, 
            simulation_requirement,
            additional_context
        )
        
        messages = [
            {"role": "system", "content": ONTOLOGY_SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ]
        
        # LLM 호출
        result = self.llm_client.chat_json(
            messages=messages,
            temperature=0.3,
            max_tokens=4096
        )
        
        # 검증 및 후처리
        result = self._validate_and_process(result)
        
        return result
    
    # LLM에 전달할 텍스트 최대 길이(5만자)
    MAX_TEXT_LENGTH_FOR_LLM = 50000
    
    def _build_user_message(
        self,
        document_texts: List[str],
        simulation_requirement: str,
        additional_context: Optional[str]
    ) -> str:
        """사용자 메시지를 구성한다."""

        # 문서 텍스트 병합
        combined_text = "\n\n---\n\n".join(document_texts)
        original_length = len(combined_text)
        
        # 5만자를 넘으면 잘라서 전달(그래프 구축 원문에는 영향 없음)
        if len(combined_text) > self.MAX_TEXT_LENGTH_FOR_LLM:
            combined_text = combined_text[:self.MAX_TEXT_LENGTH_FOR_LLM]
            combined_text += (
                f"\n\n...(원문 총 {original_length}자 중 "
                f"앞 {self.MAX_TEXT_LENGTH_FOR_LLM}자만 온톨로지 분석에 사용)..."
            )
        
        message = f"""## 시뮬레이션 요구사항

{simulation_requirement}

## 문서 내용

{combined_text}
"""
        
        if additional_context:
            message += f"""
## 추가 설명

{additional_context}
"""
        
        message += """
위 내용을 바탕으로 사회 여론 시뮬레이션에 적합한 엔터티/관계 타입을 설계하세요.

**필수 규칙**:
1. 엔터티 타입은 정확히 10개
2. 마지막 2개는 fallback 타입: Person, Organization
3. 앞 8개는 문서 맥락 기반의 구체 타입
4. 엔터티는 현실에서 발화 가능한 주체여야 하며 추상 개념은 금지
5. 속성명에 `name`, `uuid`, `group_id` 같은 예약어 사용 금지
"""
        
        return message
    
    def _validate_and_process(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """결과를 검증하고 후처리한다."""
        
        # 필수 필드 보장
        if "entity_types" not in result:
            result["entity_types"] = []
        if "edge_types" not in result:
            result["edge_types"] = []
        if "analysis_summary" not in result:
            result["analysis_summary"] = ""
        
        # 엔터티 타입 검증
        for entity in result["entity_types"]:
            if "attributes" not in entity:
                entity["attributes"] = []
            if "examples" not in entity:
                entity["examples"] = []
            # description 길이 제한(100자)
            if len(entity.get("description", "")) > 100:
                entity["description"] = entity["description"][:97] + "..."
        
        # 관계 타입 검증
        for edge in result["edge_types"]:
            if "source_targets" not in edge:
                edge["source_targets"] = []
            if "attributes" not in edge:
                edge["attributes"] = []
            if len(edge.get("description", "")) > 100:
                edge["description"] = edge["description"][:97] + "..."
        
        # 커스텀 엔터티/엣지 타입 각각 최대 10개
        MAX_ENTITY_TYPES = 10
        MAX_EDGE_TYPES = 10
        
        # fallback 타입 정의
        person_fallback = {
            "name": "Person",
            "description": "Any individual person not fitting other specific person types.",
            "attributes": [
                {"name": "full_name", "type": "text", "description": "Full name of the person"},
                {"name": "role", "type": "text", "description": "Role or occupation"}
            ],
            "examples": ["ordinary citizen", "anonymous netizen"]
        }
        
        organization_fallback = {
            "name": "Organization",
            "description": "Any organization not fitting other specific organization types.",
            "attributes": [
                {"name": "org_name", "type": "text", "description": "Name of the organization"},
                {"name": "org_type", "type": "text", "description": "Type of organization"}
            ],
            "examples": ["small business", "community group"]
        }
        
        # fallback 타입 존재 여부 확인
        entity_names = {e["name"] for e in result["entity_types"]}
        has_person = "Person" in entity_names
        has_organization = "Organization" in entity_names
        
        # 추가할 fallback 타입 목록
        fallbacks_to_add = []
        if not has_person:
            fallbacks_to_add.append(person_fallback)
        if not has_organization:
            fallbacks_to_add.append(organization_fallback)
        
        if fallbacks_to_add:
            current_count = len(result["entity_types"])
            needed_slots = len(fallbacks_to_add)
            
            # 추가 후 10개를 넘으면 기존 타입 일부 제거
            if current_count + needed_slots > MAX_ENTITY_TYPES:
                # 제거 대상 개수 계산
                to_remove = current_count + needed_slots - MAX_ENTITY_TYPES
                # 뒤에서 제거(앞쪽의 중요한 구체 타입 우선 보존)
                result["entity_types"] = result["entity_types"][:-to_remove]
            
            # fallback 타입 추가
            result["entity_types"].extend(fallbacks_to_add)
        
        # 최종 제한 재확인(방어적 처리)
        if len(result["entity_types"]) > MAX_ENTITY_TYPES:
            result["entity_types"] = result["entity_types"][:MAX_ENTITY_TYPES]
        
        if len(result["edge_types"]) > MAX_EDGE_TYPES:
            result["edge_types"] = result["edge_types"][:MAX_EDGE_TYPES]
        
        return result
    
    def generate_python_code(self, ontology: Dict[str, Any]) -> str:
        """
        온톨로지 정의를 Python 코드(ontology.py 유사 형태)로 변환한다.

        Args:
            ontology: 온톨로지 정의

        Returns:
            Python 코드 문자열
        """
        code_lines = [
            '"""',
            'Custom entity type definitions',
            'Auto-generated by MiroFish for social opinion simulation',
            '"""',
            '',
            'from pydantic import BaseModel, Field',
            'from typing import Optional',
            '',
            '',
            '# Base classes (formerly from zep_cloud)',
            'class EntityText(str):',
            '    """Text field for entity attributes."""',
            '    pass',
            '',
            'class EntityModel(BaseModel):',
            '    """Base model for entity types."""',
            '    pass',
            '',
            'class EdgeModel(BaseModel):',
            '    """Base model for edge/relation types."""',
            '    pass',
            '',
            '',
            '# ============== Entity Type Definitions ==============',
            '',
        ]
        
        # 엔터티 타입 코드 생성
        for entity in ontology.get("entity_types", []):
            name = entity["name"]
            desc = entity.get("description", f"A {name} entity.")
            
            code_lines.append(f'class {name}(EntityModel):')
            code_lines.append(f'    """{desc}"""')
            
            attrs = entity.get("attributes", [])
            if attrs:
                for attr in attrs:
                    attr_name = attr["name"]
                    attr_desc = attr.get("description", attr_name)
                    code_lines.append(f'    {attr_name}: EntityText = Field(')
                    code_lines.append(f'        description="{attr_desc}",')
                    code_lines.append(f'        default=None')
                    code_lines.append(f'    )')
            else:
                code_lines.append('    pass')
            
            code_lines.append('')
            code_lines.append('')
        
        code_lines.append('# ============== Relation Type Definitions ==============')
        code_lines.append('')
        
        # 관계 타입 코드 생성
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            # PascalCase 클래스명으로 변환
            class_name = ''.join(word.capitalize() for word in name.split('_'))
            desc = edge.get("description", f"A {name} relationship.")
            
            code_lines.append(f'class {class_name}(EdgeModel):')
            code_lines.append(f'    """{desc}"""')
            
            attrs = edge.get("attributes", [])
            if attrs:
                for attr in attrs:
                    attr_name = attr["name"]
                    attr_desc = attr.get("description", attr_name)
                    code_lines.append(f'    {attr_name}: EntityText = Field(')
                    code_lines.append(f'        description="{attr_desc}",')
                    code_lines.append(f'        default=None')
                    code_lines.append(f'    )')
            else:
                code_lines.append('    pass')
            
            code_lines.append('')
            code_lines.append('')
        
        # 타입 딕셔너리 생성
        code_lines.append('# ============== Type Config ==============')
        code_lines.append('')
        code_lines.append('ENTITY_TYPES = {')
        for entity in ontology.get("entity_types", []):
            name = entity["name"]
            code_lines.append(f'    "{name}": {name},')
        code_lines.append('}')
        code_lines.append('')
        code_lines.append('EDGE_TYPES = {')
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            class_name = ''.join(word.capitalize() for word in name.split('_'))
            code_lines.append(f'    "{name}": {class_name},')
        code_lines.append('}')
        code_lines.append('')
        
        # 엣지 source_targets 매핑 생성
        code_lines.append('EDGE_SOURCE_TARGETS = {')
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            source_targets = edge.get("source_targets", [])
            if source_targets:
                st_list = ', '.join([
                    f'{{"source": "{st.get("source", "Entity")}", "target": "{st.get("target", "Entity")}"}}'
                    for st in source_targets
                ])
                code_lines.append(f'    "{name}": [{st_list}],')
        code_lines.append('}')
        
        return '\n'.join(code_lines)
