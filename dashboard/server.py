"""
SignalFlux Dashboard v3 - 简化版服务端
只保留真实 Agent 模式，支持历史记录和 Query 跟踪
"""
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

# 添加 src 到路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from dotenv import load_dotenv
load_dotenv()

from .models import RunRequest, RunResponse, DashboardRun, DashboardStep, HistoryItem, QueryGroup
from .db import get_db


# ============ 全局状态管理 ============
class RunState:
    """当前运行状态"""
    def __init__(self):
        self.current_run_id: Optional[str] = None
        self.status: str = "idle"
        self.phase: str = ""
        self.progress: int = 0
        self.connections: List[WebSocket] = []
        
        # 缓存数据（用于 WebSocket 推送）
        self.signals: List[Dict] = []
        self.charts: Dict[str, Dict] = {}
        self.transmission_graph: Dict = {}
    
    async def broadcast(self, message: dict):
        """广播消息到所有连接"""
        dead_connections = []
        for ws in self.connections:
            try:
                await ws.send_json(message)
            except:
                dead_connections.append(ws)
        
        # 清理断开的连接
        for ws in dead_connections:
            if ws in self.connections:
                self.connections.remove(ws)
    
    def reset(self, run_id: str):
        self.current_run_id = run_id
        self.status = "running"
        self.phase = "初始化"
        self.progress = 0
        self.signals = []
        self.charts = {}
        self.transmission_graph = {}


run_state = RunState()


# ============ FastAPI App ============
async def lifespan(app: FastAPI):
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║   SignalFlux Dashboard v3 - Real Agent Mode               ║
    ╠═══════════════════════════════════════════════════════════╣
    ║  🌐 Dashboard: http://localhost:8765                      ║
    ║  📡 WebSocket: ws://localhost:8765/ws                     ║
    ║  📚 API Docs:  http://localhost:8765/docs                 ║
    ╚═══════════════════════════════════════════════════════════╝
    """)
    yield
    print("👋 Dashboard shutting down")


app = FastAPI(title="SignalFlux Dashboard v3", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============ WebSocket ============
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    run_state.connections.append(websocket)
    db = get_db()
    
    # 发送初始状态
    running_task = db.get_running_task()
    if running_task:
        steps = db.get_steps(running_task.run_id, limit=100)
        await websocket.send_json({
            "type": "init",
            "data": {
                "run_id": running_task.run_id,
                "status": running_task.status,
                "query": running_task.query,
                "steps": [s.model_dump() for s in steps],
                "signals": run_state.signals,
                "charts": run_state.charts,
                "graph": run_state.transmission_graph
            }
        })
    else:
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
    
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            
            # 处理客户端命令
            if msg.get("command") == "get_history":
                history = db.get_history(limit=50)
                await websocket.send_json({
                    "type": "history",
                    "data": [h.model_dump() for h in history]
                })
            
            elif msg.get("command") == "get_query_groups":
                groups = db.get_query_groups(limit=20)
                await websocket.send_json({
                    "type": "query_groups",
                    "data": [g.model_dump() for g in groups]
                })
            
            elif msg.get("command") == "get_run_details":
                run_id = msg.get("run_id")
                if run_id:
                    run = db.get_run(run_id)
                    steps = db.get_steps(run_id)
                    await websocket.send_json({
                        "type": "run_details",
                        "data": {
                            "run": run.model_dump() if run else None,
                            "steps": [s.model_dump() for s in steps]
                        }
                    })
    
    except WebSocketDisconnect:
        if websocket in run_state.connections:
            run_state.connections.remove(websocket)


# ============ REST API ============
@app.post("/api/run", response_model=RunResponse)
async def start_run(request: RunRequest):
    """启动新的分析任务"""
    db = get_db()
    
    # 检查是否有正在运行的任务
    running = db.get_running_task()
    if running:
        raise HTTPException(400, f"已有任务正在运行: {running.run_id}")
    
    # 创建新运行记录
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run = DashboardRun(
        run_id=run_id,
        query=request.query,
        sources=request.sources,
        status="running",
        started_at=datetime.now().isoformat()
    )
    db.create_run(run)
    
    # 重置状态
    run_state.reset(run_id)
    
    # 启动工作流
    asyncio.create_task(execute_workflow(run_id, request))
    
    return RunResponse(run_id=run_id, status="started", query=request.query)


@app.get("/api/status")
async def get_status():
    """获取当前状态"""
    return {
        "run_id": run_state.current_run_id,
        "status": run_state.status,
        "phase": run_state.phase,
        "progress": run_state.progress,
        "signal_count": len(run_state.signals)
    }


@app.get("/api/history", response_model=List[HistoryItem])
async def get_history(limit: int = 50):
    """获取历史运行列表"""
    db = get_db()
    return db.get_history(limit=limit)


@app.get("/api/query-groups", response_model=List[QueryGroup])
async def get_query_groups(limit: int = 20):
    """按 Query 分组获取历史"""
    db = get_db()
    return db.get_query_groups(limit=limit)


@app.get("/api/run/{run_id}")
async def get_run(run_id: str):
    """获取运行详情"""
    db = get_db()
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, "运行记录不存在")
    
    steps = db.get_steps(run_id)
    return {
        "run": run.model_dump(),
        "steps": [s.model_dump() for s in steps]
    }


@app.delete("/api/run/{run_id}")
async def delete_run(run_id: str, confirm: bool = False):
    """删除运行记录"""
    if not confirm:
        raise HTTPException(400, "请确认删除操作 (confirm=true)")
    
    db = get_db()
    if db.delete_run(run_id):
        return {"message": f"已删除运行记录: {run_id}"}
    raise HTTPException(404, "运行记录不存在")


@app.post("/api/run/{run_id}/rerun")
async def rerun(run_id: str):
    """重新运行相同的查询"""
    db = get_db()
    old_run = db.get_run(run_id)
    if not old_run:
        raise HTTPException(404, "运行记录不存在")
    
    # 使用相同参数创建新任务
    request = RunRequest(
        query=old_run.query,
        sources=old_run.sources
    )
    return await start_run(request)


# ============ 工作流执行 ============
async def execute_workflow(run_id: str, request: RunRequest):
    """执行真实的 SignalFlux 工作流"""
    from .integration import dashboard_callback, workflow_runner
    
    db = get_db()
    loop = asyncio.get_event_loop()
    
    async def async_broadcast(message: dict):
        """处理回调消息并广播"""
        msg_type = message.get("type")
        data = message.get("data", {})
        
        if msg_type == "progress":
            run_state.phase = data.get("phase", "")
            run_state.progress = data.get("progress", 0)
        
        elif msg_type == "step":
            # 保存到数据库
            step = DashboardStep(
                run_id=run_id,
                step_type=data.get("type", ""),
                agent=data.get("agent", ""),
                content=data.get("content", ""),
                timestamp=data.get("timestamp", datetime.now().isoformat())
            )
            db.add_step(step)
        
        elif msg_type == "signal":
            run_state.signals.append(data)
        
        elif msg_type == "chart":
            ticker = data.get("ticker")
            if ticker:
                run_state.charts[ticker] = data
        
        elif msg_type == "graph":
            run_state.transmission_graph = data
        
        # 广播到所有客户端
        await run_state.broadcast(message)
    
    # 启用回调
    dashboard_callback.enable(async_broadcast, loop)
    
    try:
        run_state.status = "running"
        
        # 在后台线程启动工作流
        sources_list = [request.sources] if request.sources else ["financial"]
        workflow_runner.run_async(
            query=request.query,
            sources=sources_list,
            wide=request.wide,
            run_state=run_state
        )
        
        # 等待工作流完成
        while workflow_runner.is_running():
            await asyncio.sleep(0.5)
        
        # 更新数据库
        db.update_run(
            run_id,
            status="completed",
            finished_at=datetime.now().isoformat(),
            signal_count=len(run_state.signals)
        )
        run_state.status = "completed"
        
        # 广播完成
        await run_state.broadcast({
            "type": "completed",
            "data": {
                "run_id": run_id,
                "signal_count": len(run_state.signals)
            }
        })
        
    except Exception as e:
        db.update_run(
            run_id,
            status="failed",
            finished_at=datetime.now().isoformat(),
            error_message=str(e)
        )
        run_state.status = "failed"
        
        await run_state.broadcast({
            "type": "error",
            "data": {"message": str(e)}
        })
    
    finally:
        dashboard_callback.disable()


# ============ 静态文件服务 ============
# React 构建产物
frontend_dist = Path(__file__).parent / "frontend" / "dist"
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
