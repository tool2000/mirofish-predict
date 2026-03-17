"""
OASIS시뮬레이션 실행
실행시뮬레이션Agent, 상태
"""

import os
import sys
import json
import time
import asyncio
import threading
import subprocess
import signal
import atexit
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from queue import Queue

from ..config import Config
from ..utils.logger import get_logger
from .local_graph_memory_updater import LocalGraphMemoryManager
from .simulation_ipc import SimulationIPCClient, CommandType, IPCResponse

logger = get_logger('mirofish.simulation_runner')

# 
_cleanup_registered = False

# 플랫폼
IS_WINDOWS = sys.platform == 'win32'


class RunnerStatus(str, Enum):
    """실행상태"""
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AgentAction:
    """Agent"""
    round_num: int
    timestamp: str
    platform: str  # twitter / reddit
    agent_id: int
    agent_name: str
    action_type: str  # CREATE_POST, LIKE_POST, etc.
    action_args: Dict[str, Any] = field(default_factory=dict)
    result: Optional[str] = None
    success: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "round_num": self.round_num,
            "timestamp": self.timestamp,
            "platform": self.platform,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "action_type": self.action_type,
            "action_args": self.action_args,
            "result": self.result,
            "success": self.success,
        }


@dataclass
class RoundSummary:
    """요약"""
    round_num: int
    start_time: str
    end_time: Optional[str] = None
    simulated_hour: int = 0
    twitter_actions: int = 0
    reddit_actions: int = 0
    active_agents: List[int] = field(default_factory=list)
    actions: List[AgentAction] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "round_num": self.round_num,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "simulated_hour": self.simulated_hour,
            "twitter_actions": self.twitter_actions,
            "reddit_actions": self.reddit_actions,
            "active_agents": self.active_agents,
            "actions_count": len(self.actions),
            "actions": [a.to_dict() for a in self.actions],
        }


@dataclass
class SimulationRunState:
    """시뮬레이션 실행상태()"""
    simulation_id: str
    runner_status: RunnerStatus = RunnerStatus.IDLE
    
    # 진행률정보
    current_round: int = 0
    total_rounds: int = 0
    simulated_hours: int = 0
    total_simulation_hours: int = 0
    
    # 플랫폼시뮬레이션(플랫폼병렬)
    twitter_current_round: int = 0
    reddit_current_round: int = 0
    twitter_simulated_hours: int = 0
    reddit_simulated_hours: int = 0
    
    # 플랫폼상태
    twitter_running: bool = False
    reddit_running: bool = False
    twitter_actions_count: int = 0
    reddit_actions_count: int = 0
    
    # 플랫폼별 완료 상태(actions.jsonl의 simulation_end 기준)
    twitter_completed: bool = False
    reddit_completed: bool = False
    
    # 요약
    rounds: List[RoundSummary] = field(default_factory=list)
    
    # ()
    recent_actions: List[AgentAction] = field(default_factory=list)
    max_recent_actions: int = 50
    
    # 
    started_at: Optional[str] = None
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None
    
    # 오류정보
    error: Optional[str] = None
    
    # ID(중지)
    process_pid: Optional[int] = None
    
    def add_action(self, action: AgentAction):
        """목록"""
        self.recent_actions.insert(0, action)
        if len(self.recent_actions) > self.max_recent_actions:
            self.recent_actions = self.recent_actions[:self.max_recent_actions]
        
        if action.platform == "twitter":
            self.twitter_actions_count += 1
        else:
            self.reddit_actions_count += 1
        
        self.updated_at = datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "simulation_id": self.simulation_id,
            "runner_status": self.runner_status.value,
            "current_round": self.current_round,
            "total_rounds": self.total_rounds,
            "simulated_hours": self.simulated_hours,
            "total_simulation_hours": self.total_simulation_hours,
            "progress_percent": round(self.current_round / max(self.total_rounds, 1) * 100, 1),
            # 플랫폼
            "twitter_current_round": self.twitter_current_round,
            "reddit_current_round": self.reddit_current_round,
            "twitter_simulated_hours": self.twitter_simulated_hours,
            "reddit_simulated_hours": self.reddit_simulated_hours,
            "twitter_running": self.twitter_running,
            "reddit_running": self.reddit_running,
            "twitter_completed": self.twitter_completed,
            "reddit_completed": self.reddit_completed,
            "twitter_actions_count": self.twitter_actions_count,
            "reddit_actions_count": self.reddit_actions_count,
            "total_actions_count": self.twitter_actions_count + self.reddit_actions_count,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "process_pid": self.process_pid,
        }
    
    def to_detail_dict(self) -> Dict[str, Any]:
        """상세정보"""
        result = self.to_dict()
        result["recent_actions"] = [a.to_dict() for a in self.recent_actions]
        result["rounds_count"] = len(self.rounds)
        return result


class SimulationRunner:
    """
    시뮬레이션 실행
    
    :
    1. OASIS시뮬레이션
    2. 실행로그, Agent
    3. 상태조회API
    4. /중지/
    """
    
    # 실행상태디렉터리
    RUN_STATE_DIR = os.path.join(
        os.path.dirname(__file__),
        '../../uploads/simulations'
    )
    
    # 디렉터리
    SCRIPTS_DIR = os.path.join(
        os.path.dirname(__file__),
        '../../scripts'
    )
    
    # 진행 중상태
    _run_states: Dict[str, SimulationRunState] = {}
    _processes: Dict[str, subprocess.Popen] = {}
    _action_queues: Dict[str, Queue] = {}
    _monitor_threads: Dict[str, threading.Thread] = {}
    _stdout_files: Dict[str, Any] = {}  #  stdout 파일
    _stderr_files: Dict[str, Any] = {}  #  stderr 파일
    
    # 그래프설정
    _graph_memory_enabled: Dict[str, bool] = {}  # simulation_id -> enabled
    
    @classmethod
    def get_run_state(cls, simulation_id: str) -> Optional[SimulationRunState]:
        """실행상태"""
        if simulation_id in cls._run_states:
            return cls._run_states[simulation_id]
        
        # 파일로드
        state = cls._load_run_state(simulation_id)
        if state:
            cls._run_states[simulation_id] = state
        return state
    
    @classmethod
    def _load_run_state(cls, simulation_id: str) -> Optional[SimulationRunState]:
        """파일로드실행상태"""
        state_file = os.path.join(cls.RUN_STATE_DIR, simulation_id, "run_state.json")
        if not os.path.exists(state_file):
            return None
        
        try:
            with open(state_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            state = SimulationRunState(
                simulation_id=simulation_id,
                runner_status=RunnerStatus(data.get("runner_status", "idle")),
                current_round=data.get("current_round", 0),
                total_rounds=data.get("total_rounds", 0),
                simulated_hours=data.get("simulated_hours", 0),
                total_simulation_hours=data.get("total_simulation_hours", 0),
                # 플랫폼
                twitter_current_round=data.get("twitter_current_round", 0),
                reddit_current_round=data.get("reddit_current_round", 0),
                twitter_simulated_hours=data.get("twitter_simulated_hours", 0),
                reddit_simulated_hours=data.get("reddit_simulated_hours", 0),
                twitter_running=data.get("twitter_running", False),
                reddit_running=data.get("reddit_running", False),
                twitter_completed=data.get("twitter_completed", False),
                reddit_completed=data.get("reddit_completed", False),
                twitter_actions_count=data.get("twitter_actions_count", 0),
                reddit_actions_count=data.get("reddit_actions_count", 0),
                started_at=data.get("started_at"),
                updated_at=data.get("updated_at", datetime.now().isoformat()),
                completed_at=data.get("completed_at"),
                error=data.get("error"),
                process_pid=data.get("process_pid"),
            )
            
            # 로드
            actions_data = data.get("recent_actions", [])
            for a in actions_data:
                state.recent_actions.append(AgentAction(
                    round_num=a.get("round_num", 0),
                    timestamp=a.get("timestamp", ""),
                    platform=a.get("platform", ""),
                    agent_id=a.get("agent_id", 0),
                    agent_name=a.get("agent_name", ""),
                    action_type=a.get("action_type", ""),
                    action_args=a.get("action_args", {}),
                    result=a.get("result"),
                    success=a.get("success", True),
                ))
            
            return state
        except Exception as e:
            logger.error(f"로드실행상태실패: {str(e)}")
            return None
    
    @classmethod
    def _save_run_state(cls, state: SimulationRunState):
        """저장실행상태파일"""
        sim_dir = os.path.join(cls.RUN_STATE_DIR, state.simulation_id)
        os.makedirs(sim_dir, exist_ok=True)
        state_file = os.path.join(sim_dir, "run_state.json")
        
        data = state.to_detail_dict()
        
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        cls._run_states[state.simulation_id] = state
    
    @classmethod
    def start_simulation(
        cls,
        simulation_id: str,
        platform: str = "parallel",  # twitter / reddit / parallel
        max_rounds: int = None,  # 시뮬레이션(선택, 시뮬레이션)
        enable_graph_memory_update: bool = False,  # Zep그래프
        graph_id: str = None  # Zep그래프ID(그래프)
    ) -> SimulationRunState:
        """
        시작시뮬레이션
        
        Args:
            simulation_id: 시뮬레이션ID
            platform: 실행플랫폼 (twitter/reddit/parallel)
            max_rounds: 시뮬레이션(선택, 시뮬레이션)
            enable_graph_memory_update: AgentZep그래프
            graph_id: Zep그래프ID(그래프)
            
        Returns:
            SimulationRunState
        """
        # 실행
        existing = cls.get_run_state(simulation_id)
        if existing and existing.runner_status in [RunnerStatus.RUNNING, RunnerStatus.STARTING]:
            raise ValueError(f"시뮬레이션이 이미 실행 중입니다: {simulation_id}")
        
        # 로드시뮬레이션설정
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")
        
        if not os.path.exists(config_path):
            raise ValueError("시뮬레이션 설정 파일이 없습니다. 먼저 /prepare API를 호출해 주세요.")
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 실행상태
        time_config = config.get("time_config", {})
        total_hours = time_config.get("total_simulation_hours", 72)
        minutes_per_round = time_config.get("minutes_per_round", 30)
        total_rounds = int(total_hours * 60 / minutes_per_round)
        
        # , 
        if max_rounds is not None and max_rounds > 0:
            original_rounds = total_rounds
            total_rounds = min(total_rounds, max_rounds)
            if total_rounds < original_rounds:
                logger.info(f": {original_rounds} -> {total_rounds} (max_rounds={max_rounds})")
        
        state = SimulationRunState(
            simulation_id=simulation_id,
            runner_status=RunnerStatus.STARTING,
            total_rounds=total_rounds,
            total_simulation_hours=total_hours,
            started_at=datetime.now().isoformat(),
        )
        
        cls._save_run_state(state)
        
        # 그래프, 
        if enable_graph_memory_update:
            if not graph_id:
                raise ValueError("그래프 graph_id")
            
            try:
                LocalGraphMemoryManager.create_updater(simulation_id, graph_id)
                cls._graph_memory_enabled[simulation_id] = True
                logger.info(f"그래프: simulation_id={simulation_id}, graph_id={graph_id}")
            except Exception as e:
                logger.error(f"그래프실패: {e}")
                cls._graph_memory_enabled[simulation_id] = False
        else:
            cls._graph_memory_enabled[simulation_id] = False
        
        # 실행( backend/scripts/ 디렉터리)
        if platform == "twitter":
            script_name = "run_twitter_simulation.py"
            state.twitter_running = True
        elif platform == "reddit":
            script_name = "run_reddit_simulation.py"
            state.reddit_running = True
        else:
            script_name = "run_parallel_simulation.py"
            state.twitter_running = True
            state.reddit_running = True
        
        script_path = os.path.join(cls.SCRIPTS_DIR, script_name)
        
        if not os.path.exists(script_path):
            raise ValueError(f"존재하지 않음: {script_path}")
        
        # 
        action_queue = Queue()
        cls._action_queues[simulation_id] = action_queue
        
        # 시작시뮬레이션
        try:
            # 실행, 
            # 로그:
            #   twitter/actions.jsonl - Twitter 로그
            #   reddit/actions.jsonl  - Reddit 로그
            #   simulation.log        - 로그
            
            cmd = [
                sys.executable,  # Python
                script_path,
                "--config", config_path,  # 설정 파일
            ]
            
            # , 파라미터
            if max_rounds is not None and max_rounds > 0:
                cmd.extend(["--max-rounds", str(max_rounds)])
            
            # 로그파일,  stdout/stderr 
            main_log_path = os.path.join(sim_dir, "simulation.log")
            main_log_file = open(main_log_path, 'w', encoding='utf-8')
            
            # ,  Windows  UTF-8 
            # ( OASIS)읽기파일질문
            env = os.environ.copy()
            env['PYTHONUTF8'] = '1'  # Python 3.7+ ,  open()  UTF-8
            env['PYTHONIOENCODING'] = 'utf-8'  #  stdout/stderr  UTF-8
            
            # 디렉터리시뮬레이션디렉터리(파일생성)
            #  start_new_session=True ,  os.killpg 
            process = subprocess.Popen(
                cmd,
                cwd=sim_dir,
                stdout=main_log_file,
                stderr=subprocess.STDOUT,  # stderr 쓰기파일
                text=True,
                encoding='utf-8',  # 
                bufsize=1,
                env=env,  #  UTF-8 
                start_new_session=True,  # , 
            )
            
            # 저장파일
            cls._stdout_files[simulation_id] = main_log_file
            cls._stderr_files[simulation_id] = None  #  stderr
            
            state.process_pid = process.pid
            state.runner_status = RunnerStatus.RUNNING
            cls._processes[simulation_id] = process
            cls._save_run_state(state)
            
            # 시작
            monitor_thread = threading.Thread(
                target=cls._monitor_simulation,
                args=(simulation_id,),
                daemon=True
            )
            monitor_thread.start()
            cls._monitor_threads[simulation_id] = monitor_thread
            
            logger.info(f"시뮬레이션시작: {simulation_id}, pid={process.pid}, platform={platform}")
            
        except Exception as e:
            state.runner_status = RunnerStatus.FAILED
            state.error = str(e)
            cls._save_run_state(state)
            raise
        
        return state
    
    @classmethod
    def _monitor_simulation(cls, simulation_id: str):
        """시뮬레이션, 로그"""
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        
        # 로그:플랫폼로그
        twitter_actions_log = os.path.join(sim_dir, "twitter", "actions.jsonl")
        reddit_actions_log = os.path.join(sim_dir, "reddit", "actions.jsonl")
        
        process = cls._processes.get(simulation_id)
        state = cls.get_run_state(simulation_id)
        
        if not process or not state:
            return
        
        twitter_position = 0
        reddit_position = 0
        
        try:
            while process.poll() is None:  # 실행
                # 읽기 Twitter 로그
                if os.path.exists(twitter_actions_log):
                    twitter_position = cls._read_action_log(
                        twitter_actions_log, twitter_position, state, "twitter"
                    )
                
                # 읽기 Reddit 로그
                if os.path.exists(reddit_actions_log):
                    reddit_position = cls._read_action_log(
                        reddit_actions_log, reddit_position, state, "reddit"
                    )
                
                # 상태
                cls._save_run_state(state)
                time.sleep(2)
            
            # , 읽기로그
            if os.path.exists(twitter_actions_log):
                cls._read_action_log(twitter_actions_log, twitter_position, state, "twitter")
            if os.path.exists(reddit_actions_log):
                cls._read_action_log(reddit_actions_log, reddit_position, state, "reddit")
            
            # 
            exit_code = process.returncode
            
            if exit_code == 0:
                state.runner_status = RunnerStatus.COMPLETED
                state.completed_at = datetime.now().isoformat()
                logger.info(f"시뮬레이션 완료: {simulation_id}")
            else:
                state.runner_status = RunnerStatus.FAILED
                # 로그파일읽기오류정보
                main_log_path = os.path.join(sim_dir, "simulation.log")
                error_info = ""
                try:
                    if os.path.exists(main_log_path):
                        with open(main_log_path, 'r', encoding='utf-8') as f:
                            error_info = f.read()[-2000:]  # 2000
                except Exception:
                    pass
                state.error = f": {exit_code}, 오류: {error_info}"
                logger.error(f"시뮬레이션실패: {simulation_id}, error={state.error}")
            
            state.twitter_running = False
            state.reddit_running = False
            cls._save_run_state(state)
            
        except Exception as e:
            logger.error(f": {simulation_id}, error={str(e)}")
            state.runner_status = RunnerStatus.FAILED
            state.error = str(e)
            cls._save_run_state(state)
        
        finally:
            # 중지그래프
            if cls._graph_memory_enabled.get(simulation_id, False):
                try:
                    LocalGraphMemoryManager.stop_updater(simulation_id)
                    logger.info(f"중지그래프: simulation_id={simulation_id}")
                except Exception as e:
                    logger.error(f"중지그래프실패: {e}")
                cls._graph_memory_enabled.pop(simulation_id, None)
            
            # 
            cls._processes.pop(simulation_id, None)
            cls._action_queues.pop(simulation_id, None)
            
            # 로그파일
            if simulation_id in cls._stdout_files:
                try:
                    cls._stdout_files[simulation_id].close()
                except Exception:
                    pass
                cls._stdout_files.pop(simulation_id, None)
            if simulation_id in cls._stderr_files and cls._stderr_files[simulation_id]:
                try:
                    cls._stderr_files[simulation_id].close()
                except Exception:
                    pass
                cls._stderr_files.pop(simulation_id, None)
    
    @classmethod
    def _read_action_log(
        cls, 
        log_path: str, 
        position: int, 
        state: SimulationRunState,
        platform: str
    ) -> int:
        """
        읽기로그파일
        
        Args:
            log_path: 로그파일
            position: 읽기
            state: 실행상태
            platform: 플랫폼 (twitter/reddit)
            
        Returns:
            읽기
        """
        # 그래프
        graph_memory_enabled = cls._graph_memory_enabled.get(state.simulation_id, False)
        graph_updater = None
        if graph_memory_enabled:
            graph_updater = LocalGraphMemoryManager.get_updater(state.simulation_id)
        
        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                f.seek(position)
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            action_data = json.loads(line)
                            
                            # 타입
                            if "event_type" in action_data:
                                event_type = action_data.get("event_type")
                                
                                #  simulation_end , 플랫폼완료
                                if event_type == "simulation_end":
                                    if platform == "twitter":
                                        state.twitter_completed = True
                                        state.twitter_running = False
                                        logger.info(f"Twitter 시뮬레이션 완료: {state.simulation_id}, total_rounds={action_data.get('total_rounds')}, total_actions={action_data.get('total_actions')}")
                                    elif platform == "reddit":
                                        state.reddit_completed = True
                                        state.reddit_running = False
                                        logger.info(f"Reddit 시뮬레이션 완료: {state.simulation_id}, total_rounds={action_data.get('total_rounds')}, total_actions={action_data.get('total_actions')}")
                                    
                                    # 플랫폼완료
                                    # 실행플랫폼, 플랫폼
                                    # 실행플랫폼, 완료
                                    all_completed = cls._check_all_platforms_completed(state)
                                    if all_completed:
                                        state.runner_status = RunnerStatus.COMPLETED
                                        state.completed_at = datetime.now().isoformat()
                                        logger.info(f"플랫폼시뮬레이션 완료: {state.simulation_id}")
                                
                                # 정보( round_end )
                                elif event_type == "round_end":
                                    round_num = action_data.get("round", 0)
                                    simulated_hours = action_data.get("simulated_hours", 0)
                                    
                                    # 플랫폼
                                    if platform == "twitter":
                                        if round_num > state.twitter_current_round:
                                            state.twitter_current_round = round_num
                                        state.twitter_simulated_hours = simulated_hours
                                    elif platform == "reddit":
                                        if round_num > state.reddit_current_round:
                                            state.reddit_current_round = round_num
                                        state.reddit_simulated_hours = simulated_hours
                                    
                                    # 플랫폼
                                    if round_num > state.current_round:
                                        state.current_round = round_num
                                    # 플랫폼
                                    state.simulated_hours = max(state.twitter_simulated_hours, state.reddit_simulated_hours)
                                
                                continue
                            
                            action = AgentAction(
                                round_num=action_data.get("round", 0),
                                timestamp=action_data.get("timestamp", datetime.now().isoformat()),
                                platform=platform,
                                agent_id=action_data.get("agent_id", 0),
                                agent_name=action_data.get("agent_name", ""),
                                action_type=action_data.get("action_type", ""),
                                action_args=action_data.get("action_args", {}),
                                result=action_data.get("result"),
                                success=action_data.get("success", True),
                            )
                            state.add_action(action)
                            
                            # 
                            if action.round_num and action.round_num > state.current_round:
                                state.current_round = action.round_num
                            
                            # 그래프, Zep
                            if graph_updater:
                                graph_updater.add_activity_from_dict(action_data, platform)
                            
                        except json.JSONDecodeError:
                            pass
                return f.tell()
        except Exception as e:
            logger.warning(f"읽기로그실패: {log_path}, error={e}")
            return position
    
    @classmethod
    def _check_all_platforms_completed(cls, state: SimulationRunState) -> bool:
        """
        플랫폼완료시뮬레이션
        
         actions.jsonl 파일플랫폼
        
        Returns:
            True 플랫폼완료
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, state.simulation_id)
        twitter_log = os.path.join(sim_dir, "twitter", "actions.jsonl")
        reddit_log = os.path.join(sim_dir, "reddit", "actions.jsonl")
        
        # 플랫폼(파일)
        twitter_enabled = os.path.exists(twitter_log)
        reddit_enabled = os.path.exists(reddit_log)
        
        # 플랫폼완료, 반환 False
        if twitter_enabled and not state.twitter_completed:
            return False
        if reddit_enabled and not state.reddit_completed:
            return False
        
        # 플랫폼완료
        return twitter_enabled or reddit_enabled
    
    @classmethod
    def _terminate_process(cls, process: subprocess.Popen, simulation_id: str, timeout: int = 10):
        """
        플랫폼
        
        Args:
            process: 
            simulation_id: 시뮬레이션ID(로그)
            timeout: ()
        """
        if IS_WINDOWS:
            # Windows:  taskkill 
            # /F = , /T = ()
            logger.info(f" (Windows): simulation={simulation_id}, pid={process.pid}")
            try:
                # 
                subprocess.run(
                    ['taskkill', '/PID', str(process.pid), '/T'],
                    capture_output=True,
                    timeout=5
                )
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    # 
                    logger.warning(f", : {simulation_id}")
                    subprocess.run(
                        ['taskkill', '/F', '/PID', str(process.pid), '/T'],
                        capture_output=True,
                        timeout=5
                    )
                    process.wait(timeout=5)
            except Exception as e:
                logger.warning(f"taskkill 실패,  terminate: {e}")
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
        else:
            # Unix: 
            #  start_new_session=True,  ID  PID
            pgid = os.getpgid(process.pid)
            logger.info(f" (Unix): simulation={simulation_id}, pgid={pgid}")
            
            #  SIGTERM 
            os.killpg(pgid, signal.SIGTERM)
            
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                # ,  SIGKILL
                logger.warning(f" SIGTERM, : {simulation_id}")
                os.killpg(pgid, signal.SIGKILL)
                process.wait(timeout=5)
    
    @classmethod
    def stop_simulation(cls, simulation_id: str) -> SimulationRunState:
        """중지시뮬레이션"""
        state = cls.get_run_state(simulation_id)
        if not state:
            raise ValueError(f"시뮬레이션존재하지 않음: {simulation_id}")
        
        if state.runner_status not in [RunnerStatus.RUNNING, RunnerStatus.PAUSED]:
            raise ValueError(f"시뮬레이션 실행: {simulation_id}, status={state.runner_status}")
        
        state.runner_status = RunnerStatus.STOPPING
        cls._save_run_state(state)
        
        # 
        process = cls._processes.get(simulation_id)
        if process and process.poll() is None:
            try:
                cls._terminate_process(process, simulation_id)
            except ProcessLookupError:
                # 존재하지 않음
                pass
            except Exception as e:
                logger.error(f"실패: {simulation_id}, error={e}")
                # 
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except Exception:
                    process.kill()
        
        state.runner_status = RunnerStatus.STOPPED
        state.twitter_running = False
        state.reddit_running = False
        state.completed_at = datetime.now().isoformat()
        cls._save_run_state(state)
        
        # 중지그래프
        if cls._graph_memory_enabled.get(simulation_id, False):
            try:
                LocalGraphMemoryManager.stop_updater(simulation_id)
                logger.info(f"중지그래프: simulation_id={simulation_id}")
            except Exception as e:
                logger.error(f"중지그래프실패: {e}")
            cls._graph_memory_enabled.pop(simulation_id, None)
        
        logger.info(f"시뮬레이션중지: {simulation_id}")
        return state
    
    @classmethod
    def _read_actions_from_file(
        cls,
        file_path: str,
        default_platform: Optional[str] = None,
        platform_filter: Optional[str] = None,
        agent_id: Optional[int] = None,
        round_num: Optional[int] = None
    ) -> List[AgentAction]:
        """
        파일 처리 중
        
        Args:
            file_path: 로그파일
            default_platform: 플랫폼(platform )
            platform_filter: 플랫폼
            agent_id:  Agent ID
            round_num: 
        """
        if not os.path.exists(file_path):
            return []
        
        actions = []
        
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                try:
                    data = json.loads(line)
                    
                    # ( simulation_start, round_start, round_end )
                    if "event_type" in data:
                        continue
                    
                    #  agent_id ( Agent )
                    if "agent_id" not in data:
                        continue
                    
                    # 플랫폼:platform, 플랫폼
                    record_platform = data.get("platform") or default_platform or ""
                    
                    # 
                    if platform_filter and record_platform != platform_filter:
                        continue
                    if agent_id is not None and data.get("agent_id") != agent_id:
                        continue
                    if round_num is not None and data.get("round") != round_num:
                        continue
                    
                    actions.append(AgentAction(
                        round_num=data.get("round", 0),
                        timestamp=data.get("timestamp", ""),
                        platform=record_platform,
                        agent_id=data.get("agent_id", 0),
                        agent_name=data.get("agent_name", ""),
                        action_type=data.get("action_type", ""),
                        action_args=data.get("action_args", {}),
                        result=data.get("result"),
                        success=data.get("success", True),
                    ))
                    
                except json.JSONDecodeError:
                    continue
        
        return actions
    
    @classmethod
    def get_all_actions(
        cls,
        simulation_id: str,
        platform: Optional[str] = None,
        agent_id: Optional[int] = None,
        round_num: Optional[int] = None
    ) -> List[AgentAction]:
        """
        플랫폼과거()
        
        Args:
            simulation_id: 시뮬레이션ID
            platform: 플랫폼(twitter/reddit)
            agent_id: Agent
            round_num: 
            
        Returns:
            목록(, )
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        actions = []
        
        # 읽기 Twitter 파일(파일 platform  twitter)
        twitter_actions_log = os.path.join(sim_dir, "twitter", "actions.jsonl")
        if not platform or platform == "twitter":
            actions.extend(cls._read_actions_from_file(
                twitter_actions_log,
                default_platform="twitter",  #  platform 
                platform_filter=platform,
                agent_id=agent_id, 
                round_num=round_num
            ))
        
        # 읽기 Reddit 파일(파일 platform  reddit)
        reddit_actions_log = os.path.join(sim_dir, "reddit", "actions.jsonl")
        if not platform or platform == "reddit":
            actions.extend(cls._read_actions_from_file(
                reddit_actions_log,
                default_platform="reddit",  #  platform 
                platform_filter=platform,
                agent_id=agent_id,
                round_num=round_num
            ))
        
        # 플랫폼파일존재하지 않음, 읽기파일
        if not actions:
            actions_log = os.path.join(sim_dir, "actions.jsonl")
            actions = cls._read_actions_from_file(
                actions_log,
                default_platform=None,  # 파일 처리 중 platform 
                platform_filter=platform,
                agent_id=agent_id,
                round_num=round_num
            )
        
        # ()
        actions.sort(key=lambda x: x.timestamp, reverse=True)
        
        return actions
    
    @classmethod
    def get_actions(
        cls,
        simulation_id: str,
        limit: int = 100,
        offset: int = 0,
        platform: Optional[str] = None,
        agent_id: Optional[int] = None,
        round_num: Optional[int] = None
    ) -> List[AgentAction]:
        """
        과거()
        
        Args:
            simulation_id: 시뮬레이션ID
            limit: 반환
            offset: 
            platform: 플랫폼
            agent_id: Agent
            round_num: 
            
        Returns:
            목록
        """
        actions = cls.get_all_actions(
            simulation_id=simulation_id,
            platform=platform,
            agent_id=agent_id,
            round_num=round_num
        )
        
        # 
        return actions[offset:offset + limit]
    
    @classmethod
    def get_timeline(
        cls,
        simulation_id: str,
        start_round: int = 0,
        end_round: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        시뮬레이션()
        
        Args:
            simulation_id: 시뮬레이션ID
            start_round: 
            end_round: 
            
        Returns:
            정보
        """
        actions = cls.get_actions(simulation_id, limit=10000)
        
        # 
        rounds: Dict[int, Dict[str, Any]] = {}
        
        for action in actions:
            round_num = action.round_num
            
            if round_num < start_round:
                continue
            if end_round is not None and round_num > end_round:
                continue
            
            if round_num not in rounds:
                rounds[round_num] = {
                    "round_num": round_num,
                    "twitter_actions": 0,
                    "reddit_actions": 0,
                    "active_agents": set(),
                    "action_types": {},
                    "first_action_time": action.timestamp,
                    "last_action_time": action.timestamp,
                }
            
            r = rounds[round_num]
            
            if action.platform == "twitter":
                r["twitter_actions"] += 1
            else:
                r["reddit_actions"] += 1
            
            r["active_agents"].add(action.agent_id)
            r["action_types"][action.action_type] = r["action_types"].get(action.action_type, 0) + 1
            r["last_action_time"] = action.timestamp
        
        # 목록
        result = []
        for round_num in sorted(rounds.keys()):
            r = rounds[round_num]
            result.append({
                "round_num": round_num,
                "twitter_actions": r["twitter_actions"],
                "reddit_actions": r["reddit_actions"],
                "total_actions": r["twitter_actions"] + r["reddit_actions"],
                "active_agents_count": len(r["active_agents"]),
                "active_agents": list(r["active_agents"]),
                "action_types": r["action_types"],
                "first_action_time": r["first_action_time"],
                "last_action_time": r["last_action_time"],
            })
        
        return result
    
    @classmethod
    def get_agent_stats(cls, simulation_id: str) -> List[Dict[str, Any]]:
        """
        Agent정보
        
        Returns:
            Agent목록
        """
        actions = cls.get_actions(simulation_id, limit=10000)
        
        agent_stats: Dict[int, Dict[str, Any]] = {}
        
        for action in actions:
            agent_id = action.agent_id
            
            if agent_id not in agent_stats:
                agent_stats[agent_id] = {
                    "agent_id": agent_id,
                    "agent_name": action.agent_name,
                    "total_actions": 0,
                    "twitter_actions": 0,
                    "reddit_actions": 0,
                    "action_types": {},
                    "first_action_time": action.timestamp,
                    "last_action_time": action.timestamp,
                }
            
            stats = agent_stats[agent_id]
            stats["total_actions"] += 1
            
            if action.platform == "twitter":
                stats["twitter_actions"] += 1
            else:
                stats["reddit_actions"] += 1
            
            stats["action_types"][action.action_type] = stats["action_types"].get(action.action_type, 0) + 1
            stats["last_action_time"] = action.timestamp
        
        # 
        result = sorted(agent_stats.values(), key=lambda x: x["total_actions"], reverse=True)
        
        return result
    
    @classmethod
    def cleanup_simulation_logs(cls, simulation_id: str) -> Dict[str, Any]:
        """
        시뮬레이션 실행로그(시작시뮬레이션)
        
        삭제파일:
        - run_state.json
        - twitter/actions.jsonl
        - reddit/actions.jsonl
        - simulation.log
        - stdout.log / stderr.log
        - twitter_simulation.db(시뮬레이션)
        - reddit_simulation.db(시뮬레이션)
        - env_status.json(상태)
        
        :삭제설정 파일(simulation_config.json) profile 파일
        
        Args:
            simulation_id: 시뮬레이션ID
            
        Returns:
            정보
        """
        import shutil
        
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        
        if not os.path.exists(sim_dir):
            return {"success": True, "message": "시뮬레이션디렉터리존재하지 않음, "}
        
        cleaned_files = []
        errors = []
        
        # 삭제파일목록(파일)
        files_to_delete = [
            "run_state.json",
            "simulation.log",
            "stdout.log",
            "stderr.log",
            "twitter_simulation.db",  # Twitter 플랫폼
            "reddit_simulation.db",   # Reddit 플랫폼
            "env_status.json",        # 상태파일
        ]
        
        # 삭제디렉터리목록(로그)
        dirs_to_clean = ["twitter", "reddit"]
        
        # 삭제파일
        for filename in files_to_delete:
            file_path = os.path.join(sim_dir, filename)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    cleaned_files.append(filename)
                except Exception as e:
                    errors.append(f"삭제 {filename} 실패: {str(e)}")
        
        # 플랫폼디렉터리진행 중로그
        for dir_name in dirs_to_clean:
            dir_path = os.path.join(sim_dir, dir_name)
            if os.path.exists(dir_path):
                actions_file = os.path.join(dir_path, "actions.jsonl")
                if os.path.exists(actions_file):
                    try:
                        os.remove(actions_file)
                        cleaned_files.append(f"{dir_name}/actions.jsonl")
                    except Exception as e:
                        errors.append(f"삭제 {dir_name}/actions.jsonl 실패: {str(e)}")
        
        # 진행 중상태
        if simulation_id in cls._run_states:
            del cls._run_states[simulation_id]
        
        logger.info(f"시뮬레이션로그완료: {simulation_id}, 삭제파일: {cleaned_files}")
        
        return {
            "success": len(errors) == 0,
            "cleaned_files": cleaned_files,
            "errors": errors if errors else None
        }
    
    # 
    _cleanup_done = False
    
    @classmethod
    def cleanup_all_simulations(cls):
        """
        실행진행 중레이션
        
        호출, 
        """
        # 
        if cls._cleanup_done:
            return
        cls._cleanup_done = True
        
        # (로그)
        has_processes = bool(cls._processes)
        has_updaters = bool(cls._graph_memory_enabled)
        
        if not has_processes and not has_updaters:
            return  # , 반환
        
        logger.info("진행 중시뮬레이션...")
        
        # 중지그래프(stop_all 로그)
        try:
            LocalGraphMemoryManager.stop_all()
        except Exception as e:
            logger.error(f"중지그래프실패: {e}")
        cls._graph_memory_enabled.clear()
        
        # 
        processes = list(cls._processes.items())
        
        for simulation_id, process in processes:
            try:
                if process.poll() is None:  # 실행
                    logger.info(f"시뮬레이션: {simulation_id}, pid={process.pid}")
                    
                    try:
                        # 플랫폼
                        cls._terminate_process(process, simulation_id, timeout=5)
                    except (ProcessLookupError, OSError):
                        # 존재하지 않음, 
                        try:
                            process.terminate()
                            process.wait(timeout=3)
                        except Exception:
                            process.kill()
                    
                    #  run_state.json
                    state = cls.get_run_state(simulation_id)
                    if state:
                        state.runner_status = RunnerStatus.STOPPED
                        state.twitter_running = False
                        state.reddit_running = False
                        state.completed_at = datetime.now().isoformat()
                        state.error = ", 시뮬레이션"
                        cls._save_run_state(state)
                    
                    #  state.json, 상태 stopped
                    try:
                        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
                        state_file = os.path.join(sim_dir, "state.json")
                        logger.info(f" state.json: {state_file}")
                        if os.path.exists(state_file):
                            with open(state_file, 'r', encoding='utf-8') as f:
                                state_data = json.load(f)
                            state_data['status'] = 'stopped'
                            state_data['updated_at'] = datetime.now().isoformat()
                            with open(state_file, 'w', encoding='utf-8') as f:
                                json.dump(state_data, f, indent=2, ensure_ascii=False)
                            logger.info(f" state.json 상태 stopped: {simulation_id}")
                        else:
                            logger.warning(f"state.json 존재하지 않음: {state_file}")
                    except Exception as state_err:
                        logger.warning(f" state.json 실패: {simulation_id}, error={state_err}")
                        
            except Exception as e:
                logger.error(f"실패: {simulation_id}, error={e}")
        
        # 파일
        for simulation_id, file_handle in list(cls._stdout_files.items()):
            try:
                if file_handle:
                    file_handle.close()
            except Exception:
                pass
        cls._stdout_files.clear()
        
        for simulation_id, file_handle in list(cls._stderr_files.items()):
            try:
                if file_handle:
                    file_handle.close()
            except Exception:
                pass
        cls._stderr_files.clear()
        
        # 진행 중
        cls._processes.clear()
        cls._action_queues.clear()
        
        logger.info("시뮬레이션 완료")
    
    @classmethod
    def register_cleanup(cls):
        """
        
        
         Flask 시작호출, 시뮬레이션
        """
        global _cleanup_registered
        
        if _cleanup_registered:
            return
        
        # Flask debug ,  reloader 진행 중(실행)
        # WERKZEUG_RUN_MAIN=true  reloader 
        #  debug , , 
        is_reloader_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
        is_debug_mode = os.environ.get('FLASK_DEBUG') == '1' or os.environ.get('WERKZEUG_RUN_MAIN') is not None
        
        #  debug ,  reloader 진행 중 debug 
        if is_debug_mode and not is_reloader_process:
            _cleanup_registered = True  # , 
            return
        
        # 저장
        original_sigint = signal.getsignal(signal.SIGINT)
        original_sigterm = signal.getsignal(signal.SIGTERM)
        # SIGHUP  Unix (macOS/Linux), Windows 
        original_sighup = None
        has_sighup = hasattr(signal, 'SIGHUP')
        if has_sighup:
            original_sighup = signal.getsignal(signal.SIGHUP)
        
        def cleanup_handler(signum=None, frame=None):
            """:시뮬레이션, 호출"""
            # 로그
            if cls._processes or cls._graph_memory_enabled:
                logger.info(f" {signum}, 시작...")
            cls.cleanup_all_simulations()
            
            # 호출,  Flask 
            if signum == signal.SIGINT and callable(original_sigint):
                original_sigint(signum, frame)
            elif signum == signal.SIGTERM and callable(original_sigterm):
                original_sigterm(signum, frame)
            elif has_sighup and signum == signal.SIGHUP:
                # SIGHUP: 
                if callable(original_sighup):
                    original_sighup(signum, frame)
                else:
                    # :
                    sys.exit(0)
            else:
                # 호출( SIG_DFL), 
                raise KeyboardInterrupt
        
        #  atexit ()
        atexit.register(cls.cleanup_all_simulations)
        
        # ()
        try:
            # SIGTERM: kill 
            signal.signal(signal.SIGTERM, cleanup_handler)
            # SIGINT: Ctrl+C
            signal.signal(signal.SIGINT, cleanup_handler)
            # SIGHUP: ( Unix )
            if has_sighup:
                signal.signal(signal.SIGHUP, cleanup_handler)
        except ValueError:
            # 진행 중 atexit
            logger.warning("(),  atexit")
        
        _cleanup_registered = True
    
    @classmethod
    def get_running_simulations(cls) -> List[str]:
        """
        실행 중시뮬레이션ID목록
        """
        running = []
        for sim_id, process in cls._processes.items():
            if process.poll() is None:
                running.append(sim_id)
        return running
    
    # ============== Interview  ==============
    
    @classmethod
    def check_env_alive(cls, simulation_id: str) -> bool:
        """
        시뮬레이션(Interview)

        Args:
            simulation_id: 시뮬레이션ID

        Returns:
            True , False 
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        if not os.path.exists(sim_dir):
            return False

        ipc_client = SimulationIPCClient(sim_dir)
        return ipc_client.check_env_alive()

    @classmethod
    def get_env_status_detail(cls, simulation_id: str) -> Dict[str, Any]:
        """
        시뮬레이션상세상태정보

        Args:
            simulation_id: 시뮬레이션ID

        Returns:
            상태,  status, twitter_available, reddit_available, timestamp
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        status_file = os.path.join(sim_dir, "env_status.json")
        
        default_status = {
            "status": "stopped",
            "twitter_available": False,
            "reddit_available": False,
            "timestamp": None
        }
        
        if not os.path.exists(status_file):
            return default_status
        
        try:
            with open(status_file, 'r', encoding='utf-8') as f:
                status = json.load(f)
            return {
                "status": status.get("status", "stopped"),
                "twitter_available": status.get("twitter_available", False),
                "reddit_available": status.get("reddit_available", False),
                "timestamp": status.get("timestamp")
            }
        except (json.JSONDecodeError, OSError):
            return default_status

    @classmethod
    def interview_agent(
        cls,
        simulation_id: str,
        agent_id: int,
        prompt: str,
        platform: str = None,
        timeout: float = 60.0
    ) -> Dict[str, Any]:
        """
        인터뷰Agent

        Args:
            simulation_id: 시뮬레이션ID
            agent_id: Agent ID
            prompt: 인터뷰질문
            platform: 플랫폼(선택)
                - "twitter": 인터뷰Twitter플랫폼
                - "reddit": 인터뷰Reddit플랫폼
                - None: 플랫폼시뮬레이션인터뷰플랫폼, 반환
            timeout: ()

        Returns:
            인터뷰

        Raises:
            ValueError: 시뮬레이션존재하지 않음실행
            TimeoutError: 
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        if not os.path.exists(sim_dir):
            raise ValueError(f"시뮬레이션존재하지 않음: {simulation_id}")

        ipc_client = SimulationIPCClient(sim_dir)

        if not ipc_client.check_env_alive():
            raise ValueError(f"시뮬레이션 실행, Interview: {simulation_id}")

        logger.info(f"Interview: simulation_id={simulation_id}, agent_id={agent_id}, platform={platform}")

        response = ipc_client.send_interview(
            agent_id=agent_id,
            prompt=prompt,
            platform=platform,
            timeout=timeout
        )

        if response.status.value == "completed":
            return {
                "success": True,
                "agent_id": agent_id,
                "prompt": prompt,
                "result": response.result,
                "timestamp": response.timestamp
            }
        else:
            return {
                "success": False,
                "agent_id": agent_id,
                "prompt": prompt,
                "error": response.error,
                "timestamp": response.timestamp
            }
    
    @classmethod
    def interview_agents_batch(
        cls,
        simulation_id: str,
        interviews: List[Dict[str, Any]],
        platform: str = None,
        timeout: float = 120.0
    ) -> Dict[str, Any]:
        """
        인터뷰Agent

        Args:
            simulation_id: 시뮬레이션ID
            interviews: 인터뷰목록,  {"agent_id": int, "prompt": str, "platform": str(선택)}
            platform: 플랫폼(선택, 인터뷰platform)
                - "twitter": 인터뷰Twitter플랫폼
                - "reddit": 인터뷰Reddit플랫폼
                - None: 플랫폼시뮬레이션Agent 인터뷰플랫폼
            timeout: ()

        Returns:
            인터뷰

        Raises:
            ValueError: 시뮬레이션존재하지 않음실행
            TimeoutError: 
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        if not os.path.exists(sim_dir):
            raise ValueError(f"시뮬레이션존재하지 않음: {simulation_id}")

        ipc_client = SimulationIPCClient(sim_dir)

        if not ipc_client.check_env_alive():
            raise ValueError(f"시뮬레이션 실행, Interview: {simulation_id}")

        logger.info(f"Interview: simulation_id={simulation_id}, count={len(interviews)}, platform={platform}")

        response = ipc_client.send_batch_interview(
            interviews=interviews,
            platform=platform,
            timeout=timeout
        )

        if response.status.value == "completed":
            return {
                "success": True,
                "interviews_count": len(interviews),
                "result": response.result,
                "timestamp": response.timestamp
            }
        else:
            return {
                "success": False,
                "interviews_count": len(interviews),
                "error": response.error,
                "timestamp": response.timestamp
            }
    
    @classmethod
    def interview_all_agents(
        cls,
        simulation_id: str,
        prompt: str,
        platform: str = None,
        timeout: float = 180.0
    ) -> Dict[str, Any]:
        """
        시뮬레이션 에이전트 단건 인터뷰를 수행한다.

        Args:
            simulation_id: 시뮬레이션 ID
            prompt: 인터뷰 질문
            platform: 플랫폼(선택)
                - "twitter": Twitter 플랫폼으로 인터뷰
                - "reddit": Reddit 플랫폼으로 인터뷰
                - None: 가능한 플랫폼 전체에서 인터뷰
            timeout: ()

        Returns:
            인터뷰
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        if not os.path.exists(sim_dir):
            raise ValueError(f"시뮬레이션존재하지 않음: {simulation_id}")

        # 설정 파일Agent정보
        config_path = os.path.join(sim_dir, "simulation_config.json")
        if not os.path.exists(config_path):
            raise ValueError(f"시뮬레이션설정존재하지 않음: {simulation_id}")

        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        agent_configs = config.get("agent_configs", [])
        if not agent_configs:
            raise ValueError(f"시뮬레이션설정에이전트: {simulation_id}")

        # 인터뷰목록
        interviews = []
        for agent_config in agent_configs:
            agent_id = agent_config.get("agent_id")
            if agent_id is not None:
                interviews.append({
                    "agent_id": agent_id,
                    "prompt": prompt
                })

        logger.info(f"Interview: simulation_id={simulation_id}, agent_count={len(interviews)}, platform={platform}")

        return cls.interview_agents_batch(
            simulation_id=simulation_id,
            interviews=interviews,
            platform=platform,
            timeout=timeout
        )
    
    @classmethod
    def close_simulation_env(
        cls,
        simulation_id: str,
        timeout: float = 30.0
    ) -> Dict[str, Any]:
        """
        시뮬레이션(중지시뮬레이션)
        
        시뮬레이션, 
        
        Args:
            simulation_id: 시뮬레이션ID
            timeout: ()
            
        Returns:
            
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        if not os.path.exists(sim_dir):
            raise ValueError(f"시뮬레이션존재하지 않음: {simulation_id}")
        
        ipc_client = SimulationIPCClient(sim_dir)
        
        if not ipc_client.check_env_alive():
            return {
                "success": True,
                "message": ""
            }
        
        logger.info(f": simulation_id={simulation_id}")
        
        try:
            response = ipc_client.send_close_env(timeout=timeout)
            
            return {
                "success": response.status.value == "completed",
                "message": "",
                "result": response.result,
                "timestamp": response.timestamp
            }
        except TimeoutError:
            # 진행 중
            return {
                "success": True,
                "message": "(, 진행 중)"
            }
    
    @classmethod
    def _get_interview_history_from_db(
        cls,
        db_path: str,
        platform_name: str,
        agent_id: Optional[int] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Interview과거"""
        import sqlite3
        
        if not os.path.exists(db_path):
            return []
        
        results = []
        
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            if agent_id is not None:
                cursor.execute("""
                    SELECT user_id, info, created_at
                    FROM trace
                    WHERE action = 'interview' AND user_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (agent_id, limit))
            else:
                cursor.execute("""
                    SELECT user_id, info, created_at
                    FROM trace
                    WHERE action = 'interview'
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (limit,))
            
            for user_id, info_json, created_at in cursor.fetchall():
                try:
                    info = json.loads(info_json) if info_json else {}
                except json.JSONDecodeError:
                    info = {"raw": info_json}
                
                results.append({
                    "agent_id": user_id,
                    "response": info.get("response", info),
                    "prompt": info.get("prompt", ""),
                    "timestamp": created_at,
                    "platform": platform_name
                })
            
            conn.close()
            
        except Exception as e:
            logger.error(f"읽기Interview과거실패 ({platform_name}): {e}")
        
        return results

    @classmethod
    def get_interview_history(
        cls,
        simulation_id: str,
        platform: str = None,
        agent_id: Optional[int] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Interview과거(읽기)
        
        Args:
            simulation_id: 시뮬레이션ID
            platform: 플랫폼타입(reddit/twitter/None)
                - "reddit": Reddit플랫폼과거
                - "twitter": Twitter플랫폼과거
                - None: 플랫폼과거
            agent_id: Agent ID(선택, Agent과거)
            limit: 플랫폼반환
            
        Returns:
            Interview과거목록
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        
        results = []
        
        # 조회플랫폼
        if platform in ("reddit", "twitter"):
            platforms = [platform]
        else:
            # platform, 조회플랫폼
            platforms = ["twitter", "reddit"]
        
        for p in platforms:
            db_path = os.path.join(sim_dir, f"{p}_simulation.db")
            platform_results = cls._get_interview_history_from_db(
                db_path=db_path,
                platform_name=p,
                agent_id=agent_id,
                limit=limit
            )
            results.extend(platform_results)
        
        # 
        results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        
        # 조회플랫폼, 
        if len(platforms) > 1 and len(results) > limit:
            results = results[:limit]
        
        return results
