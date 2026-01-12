"""
SignalFlux Dashboard - 数据库操作
"""
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any
from loguru import logger

from .models import DashboardRun, DashboardStep, HistoryItem, QueryGroup


class DashboardDB:
    """Dashboard 数据库管理"""
    
    def __init__(self, db_path: str = "data/signal_flux.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()
        logger.info(f"📊 Dashboard DB initialized at {self.db_path}")
    
    def _init_tables(self):
        """初始化表结构"""
        cursor = self.conn.cursor()
        
        # 运行记录表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dashboard_runs (
                run_id TEXT PRIMARY KEY,
                query TEXT,
                sources TEXT DEFAULT 'financial',
                status TEXT DEFAULT 'idle',
                started_at TEXT,
                finished_at TEXT,
                signal_count INTEGER DEFAULT 0,
                report_path TEXT,
                error_message TEXT
            )
        """)
        
        # 步骤日志表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dashboard_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                step_type TEXT,
                agent TEXT,
                content TEXT,
                timestamp TEXT,
                FOREIGN KEY (run_id) REFERENCES dashboard_runs(run_id)
            )
        """)
        
        # 创建索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_steps_run_id ON dashboard_steps(run_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_runs_query ON dashboard_runs(query)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_runs_status ON dashboard_runs(status)")
        
        self.conn.commit()
    
    # ========== 运行记录 CRUD ==========
    
    def create_run(self, run: DashboardRun) -> DashboardRun:
        """创建新运行记录"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO dashboard_runs (run_id, query, sources, status, started_at)
            VALUES (?, ?, ?, ?, ?)
        """, (run.run_id, run.query, run.sources, run.status, run.started_at))
        self.conn.commit()
        return run
    
    def get_run(self, run_id: str) -> Optional[DashboardRun]:
        """获取运行记录"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM dashboard_runs WHERE run_id = ?", (run_id,))
        row = cursor.fetchone()
        if row:
            return DashboardRun(**dict(row))
        return None
    
    def update_run(self, run_id: str, **kwargs) -> bool:
        """更新运行记录"""
        if not kwargs:
            return False
        
        set_clause = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [run_id]
        
        cursor = self.conn.cursor()
        cursor.execute(f"UPDATE dashboard_runs SET {set_clause} WHERE run_id = ?", values)
        self.conn.commit()
        return cursor.rowcount > 0
    
    def delete_run(self, run_id: str) -> bool:
        """删除运行记录及其步骤"""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM dashboard_steps WHERE run_id = ?", (run_id,))
        cursor.execute("DELETE FROM dashboard_runs WHERE run_id = ?", (run_id,))
        self.conn.commit()
        return cursor.rowcount > 0
    
    # ========== 步骤日志 ==========
    
    def add_step(self, step: DashboardStep) -> int:
        """添加步骤日志"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO dashboard_steps (run_id, step_type, agent, content, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (step.run_id, step.step_type, step.agent, step.content, step.timestamp))
        self.conn.commit()
        return cursor.lastrowid
    
    def get_steps(self, run_id: str, limit: int = 500) -> List[DashboardStep]:
        """获取运行的步骤日志"""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM dashboard_steps WHERE run_id = ? ORDER BY id DESC LIMIT ?",
            (run_id, limit)
        )
        rows = cursor.fetchall()
        return [DashboardStep(**dict(row)) for row in reversed(rows)]
    
    # ========== 历史记录 ==========
    
    def get_history(self, limit: int = 50) -> List[HistoryItem]:
        """获取历史运行列表"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT run_id, query, status, started_at, finished_at, signal_count
            FROM dashboard_runs
            ORDER BY started_at DESC
            LIMIT ?
        """, (limit,))
        
        items = []
        now = datetime.now()
        
        for row in cursor.fetchall():
            item = HistoryItem(**dict(row))
            
            # 计算持续时间
            if item.started_at and item.finished_at:
                try:
                    start = datetime.fromisoformat(item.started_at)
                    end = datetime.fromisoformat(item.finished_at)
                    item.duration_seconds = int((end - start).total_seconds())
                except:
                    pass
            
            # 计算距今时间
            if item.started_at:
                try:
                    start = datetime.fromisoformat(item.started_at)
                    delta = now - start
                    item.time_since_last_run = self._format_timedelta(delta)
                except:
                    pass
            
            items.append(item)
        
        return items
    
    def get_query_groups(self, limit: int = 20) -> List[QueryGroup]:
        """按 Query 分组获取历史记录"""
        cursor = self.conn.cursor()
        
        # 获取有 query 的运行，按 query 分组
        cursor.execute("""
            SELECT query, COUNT(*) as run_count, MAX(started_at) as last_run_at
            FROM dashboard_runs
            WHERE query IS NOT NULL AND query != ''
            GROUP BY query
            ORDER BY last_run_at DESC
            LIMIT ?
        """, (limit,))
        
        groups = []
        for row in cursor.fetchall():
            query = row['query']
            
            # 获取该 query 的所有运行
            cursor.execute("""
                SELECT run_id, query, status, started_at, finished_at, signal_count
                FROM dashboard_runs
                WHERE query = ?
                ORDER BY started_at DESC
            """, (query,))
            
            runs = [HistoryItem(**dict(r)) for r in cursor.fetchall()]
            
            groups.append(QueryGroup(
                query=query,
                run_count=row['run_count'],
                runs=runs,
                last_run_at=row['last_run_at']
            ))
        
        return groups
    
    def get_running_task(self) -> Optional[DashboardRun]:
        """获取当前正在运行的任务"""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM dashboard_runs WHERE status = 'running' ORDER BY started_at DESC LIMIT 1"
        )
        row = cursor.fetchone()
        if row:
            return DashboardRun(**dict(row))
        return None
    
    def _format_timedelta(self, delta: timedelta) -> str:
        """格式化时间差"""
        total_seconds = int(delta.total_seconds())
        
        if total_seconds < 60:
            return "刚刚"
        elif total_seconds < 3600:
            return f"{total_seconds // 60} 分钟前"
        elif total_seconds < 86400:
            return f"{total_seconds // 3600} 小时前"
        else:
            return f"{total_seconds // 86400} 天前"


# 全局单例
_db: Optional[DashboardDB] = None

def get_db() -> DashboardDB:
    global _db
    if _db is None:
        _db = DashboardDB()
    return _db
