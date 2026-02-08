"""
AlphaEar Dashboard - 简化版服务端
只保留真实 Agent 模式，支持历史记录和 Query 跟踪
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
from loguru import logger

# 添加 src 到路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from dotenv import load_dotenv
load_dotenv()

from .models import RunRequest, RunResponse, DashboardRun, DashboardStep, HistoryItem, QueryGroup, UserRegister, UserLogin, Token, User
from .db import get_db
from utils.database_manager import DatabaseManager
from utils.news_tools import NewsNowTools

from fastapi.security import OAuth2PasswordBearer
from fastapi import Depends, status
from passlib.context import CryptContext
from jose import JWTError, jwt

# ============ Auth Configuration ============
SECRET_KEY = os.getenv("SECRET_KEY", "alphaear-secret-key-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        user_id: int = payload.get("id")
        if username is None or user_id is None:
            raise credentials_exception
        return {"username": username, "id": str(user_id)}
    except JWTError:
        raise credentials_exception



# ============ 全局状态管理 ============
class RunContext:
    """单个运行的状态上下文"""
    def __init__(self, run_id: str, user_id: str):
        self.run_id = run_id
        self.user_id = user_id
        self.status: str = "running"
        self.phase: str = "初始化"
        self.progress: int = 0
        self.output: Optional[str] = None
        self.report_structured: Optional[dict] = None
        self.signals: List[Dict] = []
        self.charts: Dict[str, Dict] = {}
        self.transmission_graph: Dict = {}
        self.error_message: Optional[str] = None


class RunState:
    """全局运行状态管理器 (支持多并发)"""
    def __init__(self):
        # Map run_id -> RunContext
        self.runs: Dict[str, RunContext] = {}
        
        # Map user_id -> List[WebSocket]
        self.user_connections: Dict[str, List[WebSocket]] = {}
        
        # Map run_id -> user_id (Quick lookup for routing)
        self.active_run_owners: Dict[str, str] = {}
    
    def get_run(self, run_id: str) -> Optional[RunContext]:
        return self.runs.get(run_id)

    def create_context(self, run_id: str, user_id: str) -> RunContext:
        ctx = RunContext(run_id, str(user_id))
        self.runs[run_id] = ctx
        self.active_run_owners[run_id] = str(user_id)
        return ctx
    
    def add_connection(self, user_id: str, websocket: WebSocket):
        if user_id not in self.user_connections:
            self.user_connections[user_id] = []
        self.user_connections[user_id].append(websocket)
        
    def remove_connection(self, user_id: str, websocket: WebSocket):
        if user_id in self.user_connections:
            if websocket in self.user_connections[user_id]:
                self.user_connections[user_id].remove(websocket)

    async def broadcast(self, message: dict):
        """精准广播：根据 message 中的 run_id 路由给特定用户"""
        data = message.get("data", {})
        target_user_id = None
        
        # 1. 尝试从消息中获取 run_id
        run_id = data.get("run_id") if isinstance(data, dict) else None
        
        if run_id:
            # 2. 查找 run owner
            if run_id in self.active_run_owners:
                target_user_id = self.active_run_owners[run_id]
            else:
                # 尝试从 DB 恢复 (针对重启后的恢复)
                try:
                    db = get_db()
                    run = db.get_run(run_id)
                    if run:
                        self.active_run_owners[run_id] = str(run.user_id)
                        target_user_id = str(run.user_id)
                except Exception:
                    pass
        
        if not target_user_id:
            # 如果没有 run_id，无法确定目标用户
            return 

        target_connections = self.user_connections.get(str(target_user_id), [])
        
        dead_connections = []
        for ws in target_connections:
            try:
                await ws.send_json(message)
            except:
                dead_connections.append(ws)
        
        # Cleanup
        for ws in dead_connections:
            self.remove_connection(str(target_user_id), ws)

run_state = RunState()

_news_db: Optional[DatabaseManager] = None
_news_tools: Optional[NewsNowTools] = None


def get_news_tools() -> NewsNowTools:
    global _news_db, _news_tools
    if _news_tools is None:
        _news_db = DatabaseManager()
        _news_tools = NewsNowTools(_news_db)
    return _news_tools

# ... (FastAPI setup omitted in replace context if not changing) ...


# ============ FastAPI App ============
async def lifespan(app: FastAPI):
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║   DeepEar Dashboard - Real Agent Mode                     ║
    ╠═══════════════════════════════════════════════════════════╣
    ║  🌐 Dashboard: http://localhost:8765                      ║
    ║  📡 WebSocket: ws://localhost:8765/ws                     ║
    ║  📚 API Docs:  http://localhost:8765/docs                 ║
    ╚═══════════════════════════════════════════════════════════╝
    """)
    # Ensure DB tables exist on startup
    db = DatabaseManager() 
    db.close()
    
    yield
    print("👋 Dashboard shutting down")


app = FastAPI(title="DeepEar Dashboard", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============ WebSocket ============
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: Optional[str] = None):
    """WebSocket endpoint with Query Param Authentication"""
    user_id = None
    try:
        # 1. Authentication
        logger.info(f"🔌 WebSocket connection attempt. Token present: {bool(token)}, Token length: {len(token) if token else 0}")
        
        if not token:
            logger.warning("🚫 WebSocket rejected: No token provided")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
            
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            user_id = str(payload.get("id"))
            logger.info(f"✅ WebSocket token valid for user_id: {user_id}")
            if not user_id:
                raise JWTError("Missing user id in token")
        except JWTError as e:
            logger.warning(f"🚫 WebSocket rejected: JWT validation failed - {e}")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # 2. Connection Upgrade
        await websocket.accept()
        run_state.add_connection(user_id, websocket)
        db = get_db()
        
        # 3. Initial State Push (User Isolated)
        # Check if the currently running task belongs to this user
        running_task = db.get_running_task()
        
        is_user_task_running = (
            running_task 
            and running_task.user_id 
            and str(running_task.user_id) == user_id
        )

        if is_user_task_running:
            # 用户有一个正在运行的任务，获取对应的 RunContext
            ctx = run_state.get_run(running_task.run_id)
            
            # 如果内存中没有，尝试从 DB 加载
            if not ctx:
                logger.warning(f"🔄 RunContext not found for {running_task.run_id}, creating placeholder")
                ctx = run_state.create_context(running_task.run_id, user_id)
                ctx.status = running_task.status
            
            steps = db.get_steps(running_task.run_id, limit=100)
            valid_charts = {
                k: v for k, v in ctx.charts.items()
                if v and isinstance(v.get("prices"), list) and len(v.get("prices", [])) > 0
            }
            await websocket.send_json({
                "type": "init",
                "data": {
                    "run_id": running_task.run_id,
                    "status": ctx.status,
                    "query": running_task.query,
                    "phase": ctx.phase,
                    "progress": ctx.progress,
                    "steps": [s.model_dump() for s in steps],
                    "signals": ctx.signals,
                    "charts": valid_charts,
                    "graph": ctx.transmission_graph
                }
            })
        else:
            # Show idle state because system is either idle OR running someone else's task
            await websocket.send_json({
                "type": "init",
                "data": {
                    "run_id": None,
                    "status": "idle",
                    "query": None,
                    "steps": [],
                    "signals": [],
                    "charts": {},
                    "graph": {}
                }
            })
        
        # 4. Message Loop
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            
            # 处理客户端命令
            if msg.get("command") == "get_history":
                history = db.get_history(limit=50, user_id=user_id)
                await websocket.send_json({
                    "type": "history",
                    "data": [h.model_dump() for h in history]
                })
            
            elif msg.get("command") == "get_query_groups":
                groups = db.get_query_groups(limit=20, user_id=user_id)
                await websocket.send_json({
                    "type": "query_groups",
                    "data": [g.model_dump() for g in groups]
                })
            
            elif msg.get("command") == "get_run_details":
                req_run_id = msg.get("run_id")
                if req_run_id:
                    run = db.get_run(req_run_id)
                    # Security Check
                    if run and str(run.user_id) == user_id:
                        steps = db.get_steps(req_run_id)
                        await websocket.send_json({
                            "type": "run_details",
                            "data": {
                                "run": run.model_dump(),
                                "steps": [s.model_dump() for s in steps]
                            }
                        })
                    else:
                        await websocket.send_json({
                           "type": "error", "message": "Run not found or access denied" 
                        })
            
            elif msg.get("command") == "get_status":
                # 查找该用户的活跃 run
                from .integration import workflow_runner
                
                user_active_run_id = None
                for rid, uid in run_state.active_run_owners.items():
                    if str(uid) == user_id and workflow_runner.is_running(rid):
                        user_active_run_id = rid
                        break
                
                if user_active_run_id:
                    ctx = run_state.get_run(user_active_run_id)
                    if ctx:
                        db_steps = db.get_steps(user_active_run_id)
                        steps = [s.model_dump() for s in db_steps]

                        valid_charts = {
                            k: v for k, v in ctx.charts.items()
                            if v and isinstance(v.get("prices"), list) and len(v.get("prices", [])) > 0
                        }
                        
                        await websocket.send_json({
                            "type": "init",
                            "data": {
                                "run_id": user_active_run_id,
                                "status": ctx.status,
                                "phase": ctx.phase,
                                "progress": ctx.progress,
                                "steps": steps,
                                "signals": ctx.signals,
                                "charts": valid_charts,
                                "graph": ctx.transmission_graph,
                                "is_running": True
                            }
                        })
                    else:
                        await websocket.send_json({
                            "type": "init",
                            "data": {"status": "idle", "is_running": False}
                        })
                else:
                     await websocket.send_json({
                        "type": "init",
                        "data": {
                            "status": "idle",
                             "is_running": False
                        }
                    })
    
    except WebSocketDisconnect:
        if user_id:
            run_state.remove_connection(user_id, websocket)


# ============ Auth API ============

@app.post("/api/auth/register", response_model=Dict[str, str])
async def register(user: UserRegister):
    """用户注册"""
    # Use DatabaseManager explicitly for user management
    db_manager = DatabaseManager() 
    
    # Check if user exists (simple check via creating)
    existing = db_manager.get_user_by_username(user.username)
    if existing:
        raise HTTPException(status_code=400, detail="Username already registered")
    
    hashed_password = get_password_hash(user.password)
    success = db_manager.create_user(user.username, hashed_password, user.invitation_code)
    
    if not success:
        # Check if it was code error
        if not db_manager.verify_invitation_code(user.invitation_code):
             raise HTTPException(status_code=400, detail="Invalid invitation code")
        raise HTTPException(status_code=500, detail="Registration failed")
        
    return {"message": "User created successfully"}

@app.post("/api/auth/login", response_model=Token)
async def login(user: UserLogin):
    """用户登录 (JSON Body)"""
    db_manager = DatabaseManager()
    db_user = db_manager.get_user_by_username(user.username)
    
    if not db_user or not verify_password(user.password, db_user['password_hash']):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username, "id": db_user['id']}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/api/auth/me", response_model=User)
async def read_users_me(current_user: dict = Depends(get_current_user)):
    """获取当前用户信息"""
    return User(id=int(current_user['id']), username=current_user['username'])


# ============ REST API ============
@app.post("/api/run", response_model=RunResponse)
async def start_run(request: RunRequest, current_user: dict = Depends(get_current_user)):
    """启动新的分析任务"""
    db = get_db()
    
    # Concurrency enabled: We no longer block if tasks are running.
    # if run_state.status == "running":
    #     raise HTTPException(400, f"已有任务正在运行: {run_state.run_id}")
    
    # 清理数据库中的僵尸运行记录 (服务器重启后遗留的 running 状态)
    stale_running = db.get_running_task()
    if stale_running:
        logger.warning(f"⚠️ Found stale running task {stale_running.run_id}, marking as failed")
        db.update_run(stale_running.run_id, status="failed")
    
    # 创建新运行记录
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    sources_value = request.sources
    if isinstance(sources_value, list):
        sources_list = sources_value
        sources_text = ",".join(sources_value)
    else:
        sources_text = sources_value or "financial"
        sources_list = [s.strip() for s in sources_text.split(",") if s.strip()]

    run = DashboardRun(
        run_id=run_id,
        query=request.query,
        sources=sources_text,
        status="running",
        started_at=datetime.now().isoformat(),
        user_id=current_user['id']
    )
    if request.query:
        latest = db.get_latest_run_by_query(request.query, user_id=current_user['id'])
        if latest and latest.run_id != run_id:
            run.parent_run_id = latest.run_id
    db.create_run(run)
    
    # 创建运行上下文
    run_state.create_context(run_id, current_user['id'])
    
    # 启动工作流
    # 启动工作流
    asyncio.create_task(execute_workflow(run_id, request, user_id=current_user['id'], concurrency=request.concurrency))
    
    return RunResponse(run_id=run_id, status="started", query=request.query)


@app.get("/api/status")
async def get_status(run_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    """获取当前状态（支持多并发）"""
    from .integration import workflow_runner
    
    user_id = str(current_user['id'])
    target_run_id = run_id
    
    # 如果没有指定 run_id，查找用户的活跃 run
    if not target_run_id:
        for rid, uid in run_state.active_run_owners.items():
            if str(uid) == user_id and workflow_runner.is_running(rid):
                target_run_id = rid
                break
    
    if target_run_id:
        ctx = run_state.get_run(target_run_id)
        if ctx:
            return {
                "run_id": target_run_id,
                "status": ctx.status,
                "phase": ctx.phase,
                "progress": ctx.progress,
                "signal_count": len(ctx.signals),
                "chart_count": len(ctx.charts),
                "is_running": workflow_runner.is_running(target_run_id),
                "is_cancelled": workflow_runner.is_cancelled(target_run_id)
            }
    
    return {
        "run_id": None,
        "status": "idle",
        "phase": "",
        "progress": 0,
        "signal_count": 0,
        "chart_count": 0,
        "is_running": False,
        "is_cancelled": False
    }


@app.post("/api/run/cancel")
async def cancel_run(current_user: dict = Depends(get_current_user)):
    """取消当前用户正在运行的工作流"""
    from .integration import workflow_runner
    
    user_id = str(current_user['id'])
    target_run_id = None
    
    # 查找用户的活跃 run
    for rid, uid in run_state.active_run_owners.items():
        if str(uid) == user_id and workflow_runner.is_running(rid):
            target_run_id = rid
            break
    
    if target_run_id:
        if workflow_runner.cancel(target_run_id):
            # 更新 RunContext 状态
            ctx = run_state.get_run(target_run_id)
            if ctx:
                ctx.status = "cancelling"
                
            await run_state.broadcast({
                "type": "status",
                "data": {"status": "cancelling", "message": "正在取消...", "run_id": target_run_id}
            })
            return {"success": True, "message": "已发送取消请求", "run_id": target_run_id}
            
    return {"success": False, "message": "未找到您正在运行的任务"}


@app.get("/api/history", response_model=List[HistoryItem])
async def get_history(limit: int = 50, current_user: dict = Depends(get_current_user)):
    """获取历史运行列表"""
    db = get_db()
    return db.get_history(limit=limit, user_id=current_user['id'])


@app.get("/api/query-groups", response_model=List[QueryGroup])
async def get_query_groups(limit: int = 20, current_user: dict = Depends(get_current_user)):
    """按 Query 分组获取历史"""
    db = get_db()
    return db.get_query_groups(limit=limit, user_id=current_user['id'])


@app.get("/api/hot-news")
async def get_hot_news(sources: str = "cls,wallstreetcn,xueqiu", count: int = 8):
    """获取热点新闻（结构化）"""
    tools = get_news_tools()
    source_list = [s.strip() for s in sources.split(",") if s.strip()]
    data = []
    for src in source_list:
        items = tools.fetch_hot_news(src, count=count, fetch_content=False)
        data.append({
            "source": src,
            "source_name": tools.SOURCES.get(src, src),
            "items": items
        })
    return {
        "updated_at": datetime.now().isoformat(),
        "sources": data
    }


@app.post("/api/suggest-queries")
async def suggest_queries(request: dict):
    """使用 LLM 根据新闻标题生成 10 个候选 Query 供用户选择"""
    news_title = request.get("title", "")
    if not news_title:
        raise HTTPException(400, "需要提供新闻标题")
    
    try:
        import os
        from utils.llm.factory import get_model
        from agno.agent import Agent
        
        # Get model config from environment
        provider = os.getenv("LLM_PROVIDER", "deepseek")
        model_id = os.getenv("LLM_MODEL", "deepseek-chat")
        host = os.getenv('LLM_HOST', None)
        if host:
            llm = get_model(provider, model_id, host=host)
        else:
            llm = get_model(provider, model_id)
        agent = Agent(model=llm, markdown=False, tool_call_limit=3)
        
        prompt = f"""你是一位金融分析专家。基于以下新闻标题，生成 10 个不同角度的分析查询（Query）。
这些 Query 将用于驱动金融信号分析系统，需要覆盖不同的分析维度。

新闻标题：{news_title}

请生成 10 个查询，每个查询应该：
1. 从不同角度切入（如：行业影响、个股机会、风险警示、宏观关联等）
2. 简洁明确，适合作为分析任务的输入
3. 覆盖短期和中长期视角

请按以下 JSON 格式返回，只返回 JSON 数组，不要其他内容：
["查询1", "查询2", ...]"""

        response = agent.run(prompt)
        content = response.content if hasattr(response, 'content') else str(response)
        
        # Parse JSON from response
        import re
        json_match = re.search(r'\[.*\]', content, re.DOTALL)
        if json_match:
            queries = json.loads(json_match.group())
            # Allow up to 10, but accept fewer
            queries = [q for q in queries if isinstance(q, str) and q.strip()][:10]
        else:
            # Fallback: split by lines and clean
            queries = [line.strip().strip('"').strip("'") for line in content.split('\n') if line.strip()]
            queries = [q for q in queries if q and not q.startswith('[') and not q.startswith(']')][:10]
        
        # If no valid queries parsed, add the original title as fallback
        if not queries:
            queries = [news_title]
        
        return {
            "title": news_title,
            "suggestions": queries
        }
    except Exception as e:
        logger.error(f"Query suggestion failed: {e}")
        # Fallback: return basic variations
        return {
            "title": news_title,
            "suggestions": [
                f"{news_title} 对A股的影响",
                f"{news_title} 相关概念股",
                f"{news_title} 投资机会分析",
                f"{news_title} 风险提示",
                f"{news_title} 行业影响",
                news_title
            ]
        }

@app.get("/api/run/{run_id}")
async def get_run(run_id: str, current_user: dict = Depends(get_current_user)):
    """获取运行详情"""
    db = get_db()
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, "运行记录不存在")
    
    # Check ownership
    str_run_user_id = str(run.user_id) if run.user_id is not None else None
    str_current_user_id = str(current_user['id'])
    
    if str_run_user_id and str_run_user_id != str_current_user_id:
         logger.warning(f"⛔ Access denied in get_run: Run {run_id} belongs to user {str_run_user_id}, but requester is {str_current_user_id}")
         raise HTTPException(403, "无权访问此运行记录")

    steps = db.get_steps(run_id)
    return {
        "run": run.model_dump(),
        "steps": [s.model_dump() for s in steps]
    }


@app.get("/api/run/{run_id}/data")
async def get_run_data(run_id: str, current_user: dict = Depends(get_current_user)):
    """获取运行的结构化数据 (signals, charts, graph)"""
    db = get_db()
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, "运行记录不存在")

    # Check ownership
    if run.user_id and str(run.user_id) != str(current_user['id']):
         raise HTTPException(403, "无权访问此运行记录")
    
    data = db.get_run_data(run_id)
    result = data or {
        "signals": [],
        "charts": {},
        "graph": {}
    }

    # Load structured report from checkpoint if not in DB
    if "report_structured" not in result:
        try:
            from utils.checkpointing import CheckpointManager
            ckpt = CheckpointManager("reports/checkpoints", run_id)
            if ckpt.exists("report_structured.json"):
                result["report_structured"] = ckpt.load_json("report_structured.json")
        except Exception as e:
            logger.warning(f"Failed to load report_structured for {run_id}: {e}")
    
    # Filter out charts without valid prices to prevent frontend crashes
    if "charts" in result and isinstance(result["charts"], dict):
        valid_charts = {
            k: v for k, v in result["charts"].items()
            if v and isinstance(v.get("prices"), list) and len(v.get("prices", [])) > 0
        }
        result["charts"] = valid_charts
    
    # Read report content if available
    report_content = None
    report_path = run.report_path
    if report_path:
        report_file = Path(report_path)
        if not report_file.is_absolute():
            report_file = Path(__file__).parent.parent / report_file
        if report_file.exists():
            try:
                with open(report_file, "r", encoding="utf-8") as f:
                    report_content = f.read()
            except Exception as e:
                logger.error(f"Failed to read report file {report_file}: {e}")
            
    if report_content:
        # Dynamic fix for Dashboard: Convert relative chart paths to Dynamic API paths
        # Filesystem: src="charts/..." (good for local file opening)
        # Dashboard: src="/api/charts/..." (loads with Dark Theme adaptation)
        # Add timestamp to bust cache
        import time
        ts = int(time.time())
        report_content = report_content.replace('src="charts/', f'src="/api/charts/')
        # Append timestamp param. Since file usually ends with .html", we can replace .html" with .html?t=ts"
        report_content = report_content.replace('.html"', f'.html?t={ts}"')

        # Dynamic fix for Forecast Logic Box styles
        # Original: background:#f9f9f9; color:#555
        # Dashboard Dark: background:#1e293b; color:#cbd5e1
        report_content = report_content.replace('background:#f9f9f9', 'background:#1e293b')
        report_content = report_content.replace('color:#555', 'color:#cbd5e1')

    result["report_content"] = report_content
    result["report_path"] = report_path
    
    return {
        "run_id": run_id,
        **result
    }

@app.delete("/api/run/{run_id}")
async def delete_run(run_id: str, confirm: bool = False, current_user: dict = Depends(get_current_user)):
    """删除运行记录"""
    if not confirm:
        # Check ownership before confirm? Technically safer to check first.
        pass

    db = get_db()
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, "运行记录不存在")
        
    if run.user_id and str(run.user_id) != str(current_user['id']):
         raise HTTPException(403, "无权删除此运行记录")

    if not confirm:
        raise HTTPException(400, "请确认删除操作 (confirm=true)")

    
    db = get_db()
    if db.delete_run(run_id):
        return {"message": f"已删除运行记录: {run_id}"}
    raise HTTPException(404, "运行记录不存在")


@app.post("/api/run/{run_id}/rerun")
async def rerun(run_id: str, current_user: dict = Depends(get_current_user)):
    """重新运行相同的查询"""
    db = get_db()
    old_run = db.get_run(run_id)
    if not old_run:
        raise HTTPException(404, "运行记录不存在")

    if old_run.user_id and str(old_run.user_id) != str(current_user['id']):
         raise HTTPException(403, "无权访问此运行记录")
    
    # 使用相同参数创建新任务
    request = RunRequest(
        query=old_run.query,
        sources=old_run.sources
    )
    return await start_run(request, current_user)


@app.post("/api/run/{run_id}/update")
async def update_run_endpoint(run_id: str, request: RunRequest, current_user: dict = Depends(get_current_user)):
    """
    更新运行记录：基于旧 Run + 新行情生成新报告
    request.query 可用于传递附加指令
    """
    db = get_db()
    
    # Check current running state
    # Concurrency: allow multiple
    # if run_state.status == "running":
    #     raise HTTPException(400, "已有任务正在运行，请稍候")

    old_run = db.get_run(run_id)
    if not old_run:
        raise HTTPException(404, "运行记录不存在")
    
    # Create placeholder run entry (actual ID created by workflow, but let's pre-announce)
    # Actually workflow.update_run creates the new ID.
    # To conform to UI expectations, we might want to return the 'future' ID or just start it.
    # But integration logic makes it tricky to know ID upfront.
    # Simplified approach: We let the workflow create it, and UI listens to WebSocket for 'init' or 'connected'.
    # HOWEVER, run_state needs an ID to broadcast correctly.
    
    # Generate the REAL ID here to ensure alignment
    new_run_id = datetime.now().strftime('%Y%m%d_%H%M%S')
    # 创建运行上下文
    run_state.create_context(new_run_id, current_user['id'])

    # Create run record upfront so UI/DB can track status
    new_run = DashboardRun(
        run_id=new_run_id,
        query=old_run.query,
        sources=old_run.sources,
        status="running",
        started_at=datetime.now().isoformat(),
        parent_run_id=run_id,
        user_id=current_user['id']
    )
    db.create_run(new_run)
    
    asyncio.create_task(execute_update_workflow(run_id, request.query, new_run_id, user_id=str(current_user['id'])))
    return {"message": "Update started", "base_run_id": run_id, "run_id": new_run_id}


@app.get("/api/charts/{filename:path}")
async def get_chart_dynamic(filename: str):
    """
    动态渲染图表接口:
    - 读取原始 HTML 图表文件
    - 强制应用 'dark' 主题和 'transparent' 背景
    - 这是为了适配 Dashboard 的深色模式，同时不修改原始文件（保持本地查看时的 Light 模式）
    """
    file_path = Path("reports/charts") / filename
    if not file_path.exists():
        # Try without strict path checking just in case
        raise HTTPException(404, "Chart not found")
        
    try:
        import re
        content = file_path.read_text(encoding="utf-8")
        
        # 1. 注入背景色透明 (Inject into option object)
        # 查找 option 定义，通常 pyecharts 生成: var option_xxx = {
        # 我们替换为 { backgroundColor: 'transparent',
        # 1. 注入背景色 (Inject into option object)
        # 使用 Dashboard 深色背景 #0f172a (Slate-900)
        TARGET_BG = "#0f172a"
        
        if "mxGraphModel" in content:
             # Draw.io specific post-processing
             # 1. Remove internal title to save space
             content = re.sub(r'<h2>.*?</h2>', '', content, flags=re.DOTALL)
             
             # 2. Optimize body style for centering and fitting
             new_body_style = (
                 f"body {{ font-family: sans-serif; padding: 10px; margin: 0; "
                 f"display: flex; justify-content: center; align-items: center; "
                 f"min-height: 100vh; overflow: hidden; background: {TARGET_BG} !important; }}"
             )
             content = re.sub(r'body\s*\{[^}]*\}', new_body_style, content)
             
             # 3. Ensure mxgraph container is responsive
             content = re.sub(
                 r'\.mxgraph\s*\{[^}]*\}',
                 f".mxgraph {{ border: 1px solid #334155; background: #fff; width: 100%; max-width: 100%; }}",
                 content
             )
             
             # 4. Inject center config if missing
             if '"center": true' not in content:
                  content = content.replace('"nav": true', '"nav": true, "center": true')

        else:
             # Standard ECharts post-processing
             if "option_" in content and " = {" in content:
                  content = re.sub(r"(var option_[a-zA-Z0-9_]+ = \{)", f"\\1 \\n    backgroundColor: '{TARGET_BG}',", content)
             
             # 2. 切换 ECharts 主题
             content = content.replace(", 'white',", ", 'dark',")
             content = content.replace(", 'light',", ", 'dark',")
             
             # ... logic ...
             if ", 'dark'," not in content:
                  content = re.sub(r",\s*'light',\s*", ", 'dark', ", content)
                  content = re.sub(r",\s*'white',\s*", ", 'dark', ", content)
             
             # 3. 额外优化
             content = content.replace('"backgroundColor": "white"', f'"backgroundColor": "{TARGET_BG}"')
             content = content.replace('"backgroundColor": "transparent"', f'"backgroundColor": "{TARGET_BG}"')

        # 4. 关键：强制 HTML body 背景 (Common for all)
        style_inject = f"""
        <style>
            html, body {{ background: {TARGET_BG} !important; background-color: {TARGET_BG} !important; }}
            .chart-container {{ background: {TARGET_BG} !important; background-color: {TARGET_BG} !important; }}
        </style>
        """
        if "</head>" in content:
            content = content.replace("</head>", f"{style_inject}\n</head>")
        else:
            content = style_inject + content
            
        # 5. JS 强制清除
        js_inject = f"""
        <script>
            try {{
                document.body.style.backgroundColor = "{TARGET_BG}";
                document.documentElement.style.backgroundColor = "{TARGET_BG}";
            }} catch(e) {{}}
        </script>
        """
        content += js_inject

        return HTMLResponse(content=content)
    except Exception as e:
        logger.error(f"Failed to process chart {filename}: {e}")
        try:
            return FileResponse(file_path)
        except Exception as fallback_e:
            logger.error(f"Fallback also failed for {filename}: {fallback_e}")
            raise HTTPException(500, f"Chart rendering failed: {e}")

@app.get("/api/run/{run_id}/export")
async def export_report(run_id: str, view: bool = False):
    """
    导出单一文件报告:
    - 读取原始 HTML 报告
    - 将所有 iframe 引用的图表转换为 base64 编码内联
    - 返回可直接打开的单文件 HTML
    """
    import base64
    import re
    from fastapi.responses import Response
    
    db = get_db()
    
    # 1. Get run and report path
    run = db.get_run(run_id)
    if not run or not run.report_path:
        # Fallback: try to find report by pattern if not in DB
        # This handles cases where old runs might not have path saved, or path mismatch
        report_files = list(Path("reports").glob(f"*{run_id}*.html"))
        if report_files:
            report_path = report_files[0]
        else:
            raise HTTPException(404, "Report not found")
    else:
        report_path = Path(run.report_path)
    
    if not report_path.exists():
        raise HTTPException(404, f"Report file not found: {report_path}")

    try:
        # 2. Read content
        html_content = report_path.read_text(encoding="utf-8")
        
        # 3. Inline iframes
        # Function to replace relative src with base64 data URI
        def replace_iframe_src(match):
            rel_src = match.group(1)
            # iframe path is relative to the report file
            # report is in reports/, chart is in reports/charts/
            # rel_src is usually "charts/xxx.html"
            chart_path = report_path.parent / rel_src
            
            if chart_path.exists():
                try:
                    # Read chart content
                    chart_content = chart_path.read_text(encoding="utf-8")
                    
                    # Apply the same dark mode optimization as the server does (optional but good)
                    # We can reuse the logic partially by simple regex replacement on the content string
                    # Or just use it raw. Let's start with raw but ensure background is handled if possible.
                    # Since we are exporting, let's keep it robust and just embed what is there, 
                    # relying on the chart file itself.
                    # Note: server.py /api/charts logic is "on-the-fly". 
                    # If we want the exported file to look like the dashboard, we should mimic that modification.
                    # For now, let's just embed. The Draw.io logic is dynamic in server, so the file on disk is raw.
                    # We should apply the Draw.io fix here too if we want the exported report to look good!
                    
                    # Export logic: use white background for better compatibility/printing
                    TARGET_BG = "#ffffff"
                    
                    # Apply layout optimization but keep white background
                    if "mxGraphModel" in chart_content:
                        # Draw.io fix (keep compact layout but white bg)
                        chart_content = re.sub(r'<h2>.*?</h2>', '', chart_content, flags=re.DOTALL)
                        if '"center": true' not in chart_content:
                             chart_content = chart_content.replace('"nav": true', '"nav": true, "center": true')
                        
                        new_body_style = (
                             f"body {{ font-family: sans-serif; padding: 10px; margin: 0; "
                             f"display: flex; justify-content: center; align-items: center; "
                             f"min-height: 100vh; overflow: hidden; background: {TARGET_BG}; }}"
                        )
                        chart_content = re.sub(r'body\s*\{[^}]*\}', new_body_style, chart_content)
                    
                    elif "option_" in chart_content:
                        # ECharts: ensures white background
                        chart_content = chart_content.replace('"backgroundColor": "#0f172a"', '"backgroundColor": "#ffffff"')
                        chart_content = chart_content.replace('"backgroundColor": "transparent"', '"backgroundColor": "#ffffff"')

                    # Encode
                    b64 = base64.b64encode(chart_content.encode('utf-8')).decode('utf-8')
                    return f'src="data:text/html;base64,{b64}"'
                except Exception as e:
                    logger.warning(f"Failed to inline chart {rel_src}: {e}")
                    return match.group(0)
            else:
                return match.group(0)

        # Pattern: look for src="charts/..."
        # We assume standard formatting from report_agent
        optimized_html = re.sub(r'src="(charts/[^"]+)"', replace_iframe_src, html_content)
        
        # 4. Add Export Notice
        notice_html = f"""
        <div style="text-align: center; padding: 40px 20px; font-size: 13px; color: #64748b; border-top: 1px solid #eee; margin-top: 50px;">
            <p>AlphaEar Intelligence Analysis Report • Standalone View</p>
            <p>Generation Date: <span id="export-date"></span></p>
            <script>document.getElementById('export-date').innerText = new Date().toLocaleString();</script>
        </div>
        </body>
        """
        optimized_html = optimized_html.replace("</body>", notice_html)
        
        filename = f"AlphaEar_Report_{run_id}.html"
        
        from fastapi.responses import HTMLResponse
        if view:
            return HTMLResponse(content=optimized_html)
        else:
            return Response(
                content=optimized_html,
                media_type="text/html",
                headers={
                    "Content-Disposition": f"attachment; filename={filename}"
                }
            )
            
    except Exception as e:
        logger.error(f"Export failed: {e}")
        raise HTTPException(500, f"Export failed: {e}")

async def execute_update_workflow(base_run_id: str, user_query: Optional[str], new_run_id: str, user_id: str = None):
    """Execute update logic"""
    from .integration import dashboard_callback, workflow_runner
    db = get_db()
    loop = asyncio.get_event_loop()
    
    # 获取当前运行上下文
    ctx = run_state.get_run(new_run_id)
    if not ctx:
        ctx = run_state.create_context(new_run_id, user_id or "unknown")
    
    async def async_broadcast(message: dict):
        msg_type = message.get("type")
        data = message.get("data", {})
        
        # 从消息中获取 run_id 以支持并发
        msg_run_id = data.get("run_id") or new_run_id
        msg_ctx = run_state.get_run(msg_run_id)
        if not msg_ctx:
            msg_ctx = ctx

        if msg_type == "progress":
            msg_ctx.phase = data.get("phase", "")
            msg_ctx.progress = data.get("progress", 0)
        elif msg_type == "step":
            step_run_id = data.get("run_id") or new_run_id
            step = DashboardStep(
                run_id=step_run_id,
                step_type=data.get("type", ""),
                agent=data.get("agent", ""),
                content=data.get("content", ""),
                timestamp=data.get("timestamp", datetime.now().isoformat())
            )
            db.add_step(step)

        await run_state.broadcast(message)

    dashboard_callback.enable(async_broadcast, loop)
    
    try:
        ctx.status = "running"
        workflow_runner.update_run_async(
            base_run_id, 
            run_state=ctx, 
            user_query=user_query, 
            new_run_id=new_run_id,
            user_id=user_id
        )
        
        while workflow_runner.is_running(new_run_id):
            await asyncio.sleep(0.5)
            
        # Post-processing: Sync the newly created run to SQLite
        try:
            from utils.checkpointing import CheckpointManager
            ckpt = CheckpointManager("reports/checkpoints", new_run_id)
            state = ckpt.load_json("state.json") if ckpt.exists("state.json") else {}

            # Load updated signals from checkpoint
            analyzed_signals = ckpt.load_json("analyzed_signals.json") if ckpt.exists("analyzed_signals.json") else []

            # Fallback to base run data if needed
            base_data = db.get_run_data(base_run_id) or {}
            signals = analyzed_signals or base_data.get("signals", [])

            # Rebuild charts with latest prices when possible
            charts: Dict[str, Dict] = dict(base_data.get("charts", {}) or {})
            try:
                workflow = workflow_runner._ensure_workflow()
                stock_tools = workflow.trend_agent.stock_toolkit._stock_tools
                end_date = datetime.now().strftime('%Y-%m-%d')
                start_date = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
                updated_tickers = set()
                for signal in signals:
                    for item in signal.get("impact_tickers", []) or []:
                        if isinstance(item, dict):
                            ticker_code = item.get("ticker")
                            ticker_name = item.get("name")
                        else:
                            ticker_code = str(item)
                            ticker_name = str(item)
                        if not ticker_code or ticker_code in updated_tickers:
                            continue
                        try:
                            df = stock_tools.get_stock_price(ticker_code, start_date, end_date)
                            if df is not None and not df.empty:
                                chart_data = workflow_runner._format_chart_from_df(
                                    ticker_code,
                                    ticker_name or ticker_code,
                                    df,
                                    news_text=signal.get("summary") or signal.get("title", ""),
                                    prediction_logic=signal.get("summary")
                                )
                                charts[ticker_code] = chart_data
                                updated_tickers.add(ticker_code)
                        except Exception as e:
                            logger.warning(f"Chart refresh failed for {ticker_code}: {e}")
            except Exception as e:
                logger.warning(f"Chart rebuild skipped: {e}")

            structured = None
            if ckpt.exists("report_structured.json"):
                structured = ckpt.load_json("report_structured.json")

            run_data = {
                "signals": signals,
                "charts": charts,
                "graph": base_data.get("graph", {}),
                "report_structured": structured
            }
            db.save_run_data(new_run_id, run_data)

            db.update_run(
                new_run_id,
                status=state.get("status", "completed"),
                finished_at=state.get("finished_at"),
                report_path=state.get("output"),
                signal_count=len(signals)
            )

            ctx.output = state.get("output")
            ctx.status = "completed"
            await run_state.broadcast({
                "type": "completed",
                "data": {"run_id": new_run_id, "parent_run_id": base_run_id}
            })
            logger.info(f"✅ Synced updated run {new_run_id} to DB")
        except Exception as e:
            logger.error(f"Failed to sync update to DB: {e}")
        
    except Exception as e:
        ctx.status = "failed"
        await run_state.broadcast({"type": "error", "data": {"message": str(e), "run_id": new_run_id}})
    finally:
        # Only disable callback if NO workflows are running (to support concurrency)
        if not workflow_runner.is_running():
            dashboard_callback.disable()


# ============ 工作流执行 ============
async def execute_workflow(run_id: str, request: RunRequest, user_id: str = None, concurrency: int = 5):
    """执行真实的 AlphaEar 工作流"""
    from .integration import dashboard_callback, workflow_runner
    
    db = get_db()
    loop = asyncio.get_event_loop()
    
    # 获取当前运行上下文
    ctx = run_state.get_run(run_id)
    if not ctx:
        ctx = run_state.create_context(run_id, user_id or "unknown")
    
    async def async_broadcast(message: dict):
        """处理回调消息并广播"""
        msg_type = message.get("type")
        data = message.get("data", {})
        
        # 从消息中获取 run_id 以支持并发
        msg_run_id = data.get("run_id") or run_id
        msg_ctx = run_state.get_run(msg_run_id)
        if not msg_ctx:
            msg_ctx = ctx  # fallback
        
        if msg_type == "progress":
            msg_ctx.phase = data.get("phase", "")
            msg_ctx.progress = data.get("progress", 0)
        
        elif msg_type == "step":
            step_run_id = data.get("run_id") or run_id
            step = DashboardStep(
                run_id=step_run_id,
                step_type=data.get("type", ""),
                agent=data.get("agent", ""),
                content=data.get("content", ""),
                timestamp=data.get("timestamp", datetime.now().isoformat())
            )
            db.add_step(step)
        
        elif msg_type == "signal":
            msg_ctx.signals.append(data)
        
        elif msg_type == "chart":
            ticker = data.get("ticker")
            if ticker:
                msg_ctx.charts[ticker] = data
        
        elif msg_type == "graph":
            msg_ctx.transmission_graph = data
        
        # 广播到对应用户
        await run_state.broadcast(message)
    
    # 启用回调
    dashboard_callback.enable(async_broadcast, loop)
    
    try:
        ctx.status = "running"
        
        # 在后台线程启动工作流
        sources_value = request.sources
        if isinstance(sources_value, list):
            sources_list = sources_value
        else:
            sources_text = sources_value or "financial"
            sources_list = [s.strip() for s in sources_text.split(",") if s.strip()]
        
        workflow_runner.run_async(
            query=request.query,
            sources=sources_list,
            wide=request.wide,
            depth=request.depth,
            run_state=ctx,  # 传递 RunContext 而非全局 run_state
            user_id=user_id,
            run_id=run_id,
            concurrency=concurrency
        )
        
        # 等待工作流完成
        while workflow_runner.is_running(run_id):
            await asyncio.sleep(0.5)
        
        # 更新数据库
        db.update_run(
            run_id,
            status="completed",
            finished_at=datetime.now().isoformat(),
            signal_count=len(ctx.signals),
            report_path=ctx.output
        )
        
        # 保存结构化数据 (用于交互式渲染和对比)
        logger.info(f"📊 Saving run data: {len(ctx.signals)} signals, {len(ctx.charts)} charts")
        run_data = {
            "signals": ctx.signals,
            "charts": ctx.charts,
            "graph": ctx.transmission_graph,
            "report_structured": ctx.report_structured
        }
        db.save_run_data(run_id, run_data)
        
        ctx.status = "completed"
        
        # 广播完成
        await run_state.broadcast({
            "type": "completed",
            "data": {
                "run_id": run_id,
                "signal_count": len(ctx.signals)
            }
        })
        
    except Exception as e:
        db.update_run(
            run_id,
            status="failed",
            finished_at=datetime.now().isoformat(),
            error_message=str(e)
        )
        ctx.status = "failed"
        
        await run_state.broadcast({
            "type": "error",
            "data": {"message": str(e), "run_id": run_id}
        })
    
    finally:
        # 只在没有其他工作流运行时禁用回调
        if not workflow_runner.is_running():
            dashboard_callback.disable()


# ============ 静态文件服务 ============
# React 构建产物
frontend_dist = Path(__file__).parent / "frontend" / "dist"
reports_dir = Path("reports")
if reports_dir.exists():
    app.mount("/reports", StaticFiles(directory=reports_dir), name="reports")

if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")
    
    @app.get("/")
    async def serve_frontend():
        return FileResponse(frontend_dist / "index.html")
    
    @app.get("/{path:path}")
    async def serve_frontend_routes(path: str):
        # 处理 React Router 路由
        file_path = frontend_dist / path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(frontend_dist / "index.html")
else:
    @app.get("/")
    async def no_frontend():
        return {
            "message": "前端未构建",
            "hint": "请运行: cd dashboard/frontend && npm run build"
        }


# ============ 入口 ============
if __name__ == "__main__":
    uvicorn.run(
        "dashboard.server:app",
        host="0.0.0.0",
        port=8765,
        reload=True
    )
