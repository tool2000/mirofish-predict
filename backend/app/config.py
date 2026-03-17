"""
설정 관리
프로젝트 루트의 `.env` 파일에서 설정을 통합 로드합니다.
"""

import os
from dotenv import load_dotenv

# 프로젝트 루트의 `.env` 파일 로드
# 경로: MiroFish/.env (backend/app/config.py 기준 상대 경로)
project_root_env = os.path.join(os.path.dirname(__file__), '../../.env')

if os.path.exists(project_root_env):
    load_dotenv(project_root_env, override=True)
else:
    # 루트에 `.env`가 없으면 시스템 환경 변수를 사용(운영 환경용)
    load_dotenv(override=True)


class Config:
    """Flask 설정 클래스"""
    
    # Flask 설정
    SECRET_KEY = os.environ.get('SECRET_KEY', 'mirofish-secret-key')
    DEBUG = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'
    
    # JSON 설정 - ASCII 이스케이프 비활성화(문자가 `\\uXXXX` 대신 그대로 표시)
    JSON_AS_ASCII = False
    
    # LLM 설정(OpenAI 형식으로 통일)
    LLM_API_KEY = os.environ.get('LLM_API_KEY', 'not-needed')
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'http://localhost:8080/v1')
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', 'local-model')
    
    # Kuzu 그래프 DB (로컬)
    KUZU_DB_DIR = os.environ.get('KUZU_DB_DIR',
        os.path.join(os.path.dirname(__file__), '../data/kuzu_db'))

    # kg-gen (LiteLLM 포맷)
    KGGEN_MODEL = os.environ.get('KGGEN_MODEL', 'openai/local-model')

    # 수렴 조기종료
    CONVERGENCE_THRESHOLD = float(os.environ.get('CONVERGENCE_THRESHOLD', '0.05'))
    CONVERGENCE_CHECK_INTERVAL = int(os.environ.get('CONVERGENCE_CHECK_INTERVAL', '5'))

    # 파일 업로드 설정
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '../uploads')
    ALLOWED_EXTENSIONS = {'pdf', 'md', 'txt', 'markdown'}
    
    # 텍스트 처리 설정
    DEFAULT_CHUNK_SIZE = 500  # 기본 청크 크기
    DEFAULT_CHUNK_OVERLAP = 50  # 기본 청크 겹침 크기
    
    # OASIS 시뮬레이션 설정
    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get('OASIS_DEFAULT_MAX_ROUNDS', '10'))
    OASIS_SIMULATION_DATA_DIR = os.path.join(os.path.dirname(__file__), '../uploads/simulations')
    
    # OASIS 플랫폼별 사용 가능 액션
    OASIS_TWITTER_ACTIONS = [
        'CREATE_POST', 'LIKE_POST', 'REPOST', 'FOLLOW', 'DO_NOTHING', 'QUOTE_POST'
    ]
    OASIS_REDDIT_ACTIONS = [
        'LIKE_POST', 'DISLIKE_POST', 'CREATE_POST', 'CREATE_COMMENT',
        'LIKE_COMMENT', 'DISLIKE_COMMENT', 'SEARCH_POSTS', 'SEARCH_USER',
        'TREND', 'REFRESH', 'DO_NOTHING', 'FOLLOW', 'MUTE'
    ]
    
    # Report Agent 설정
    REPORT_AGENT_MAX_TOOL_CALLS = int(os.environ.get('REPORT_AGENT_MAX_TOOL_CALLS', '5'))
    REPORT_AGENT_MAX_REFLECTION_ROUNDS = int(os.environ.get('REPORT_AGENT_MAX_REFLECTION_ROUNDS', '2'))
    REPORT_AGENT_TEMPERATURE = float(os.environ.get('REPORT_AGENT_TEMPERATURE', '0.5'))
    
    @classmethod
    def validate(cls):
        """필수 설정 검증"""
        errors = []
        if not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY가 설정되지 않았습니다.")
        return errors


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
