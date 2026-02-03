"""
AlphaEar Dashboard - 数据库模型
存储运行历史和步骤日志
"""
from datetime import datetime
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel


class DashboardRun(BaseModel):
    """运行记录"""
    run_id: str
    query: Optional[str] = None
    sources: str = "financial"
    status: str = "idle"  # idle/running/completed/failed
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    signal_count: int = 0
    report_path: Optional[str] = None
    error_message: Optional[str] = None
    parent_run_id: Optional[str] = None  # Parent run ID for updates/versions
    user_id: Optional[str] = None


class DashboardStep(BaseModel):
    """步骤日志"""
    id: Optional[int] = None
    run_id: str
    step_type: str  # system/thought/tool_call/result/signal/error/phase
    agent: str  # System/TrendAgent/FinAgent/ForecastAgent/ReportAgent/IntentAgent
    content: str
    timestamp: str


class RunRequest(BaseModel):
    """运行请求"""
    query: Optional[str] = None
    sources: Union[str, List[str]] = "financial"
    wide: int = 10
    depth: Union[int, str] = "auto"
    concurrency: int = 1


class RunResponse(BaseModel):
    """运行响应"""
    run_id: str
    status: str
    query: Optional[str] = None


class HistoryItem(BaseModel):
    """历史记录项"""
    run_id: str
    query: Optional[str] = None
    status: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    signal_count: int = 0
    duration_seconds: Optional[int] = None
    time_since_last_run: Optional[str] = None  # "2天前", "3小时前" 等
    parent_run_id: Optional[str] = None
    report_path: Optional[str] = None


class QueryGroup(BaseModel):
    """Query 分组 - 用于跟踪同一查询的多次运行"""
    query: str
    run_count: int
    runs: List[HistoryItem]
    last_run_at: Optional[str] = None


class UserRegister(BaseModel):
    username: str
    password: str
    invitation_code: str


class UserLogin(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str


class User(BaseModel):
    id: int
    username: str
    created_at: Optional[str] = None
