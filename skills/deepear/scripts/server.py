import sys
from pathlib import Path
import os
from typing import Optional, Union

# Dynamic Project Root Discovery
def setup_environment():
    """
    Automatically locate project root based on marker file (pyproject.toml).
    Allows the skill to be moved anywhere within the project or run from arbitrary CWD.
    """
    current_path = Path(__file__).resolve()
    
    # Walk up looking for pyproject.toml
    root = None
    for parent in [current_path] + list(current_path.parents):
        if (parent / "pyproject.toml").exists() and (parent / "src").exists():
            root = parent
            break
    
    # Fallback 1: Search for 'DeepEar' directory name in path hierarchy
    if not root:
        for parent in [current_path] + list(current_path.parents):
            if parent.name == "DeepEar" and (parent / "src").exists():
                root = parent
                break

    # Fallback 2: Hardcoded relative path (legacy/last resort)
    if not root:
        root = Path(__file__).parent.parent.parent.parent
        
    # 1. Add src to sys.path
    src_path = root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))
        
    # 2. Add root to to sys.path (for root-relative imports if any)
    if str(root) not in sys.path:
        sys.path.insert(1, str(root))
        
    return root

root_dir = setup_environment()

# Ensure CWD is project root (Critical for .env, database, logs, reports paths)
if root_dir and root_dir.exists():
    try:
        os.chdir(str(root_dir))
    except Exception:
        pass

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import uvicorn
import asyncio
import uuid
from datetime import datetime

# Try importing workflow
try:
    from main_flow import SignalFluxWorkflow
except ImportError:
    # If standard import fails, try package-style import
    try:
        from src.main_flow import SignalFluxWorkflow
    except ImportError as e:
        print(f"❌ Critical Error: Could not import SignalFluxWorkflow. sys.path: {sys.path}")
        raise e

app = FastAPI(title="DeepEar Analysis Skill")

# Simple in-memory job store
# In production, use Redis or Database
jobs = {}

class AnalyzeRequest(BaseModel):
    query: Optional[str] = None
    sources: Optional[str] = "all"
    wide: Optional[int] = 10
    depth: Optional[Union[int, str]] = "auto"
    concurrency: Optional[int] = 5
    update_from: Optional[str] = None

class JobResponse(BaseModel):
    job_id: str
    status: str
    submitted_at: str

class JobStatus(BaseModel):
    job_id: str
    status: str
    result: Optional[dict] = None
    error: Optional[str] = None
    timestamp: str

def run_workflow_task(job_id: str, request: AnalyzeRequest, root_dir: Path):
    """Background task to run the workflow"""
    try:
        # Ensure we are in project root for this thread/process context
        if root_dir and root_dir.exists():
            os.chdir(str(root_dir))
            
        jobs[job_id]["status"] = "running"
        
        # Initialize workflow
        workflow = SignalFluxWorkflow()
        
        report_path = None
        
        if request.update_from:
            # Tracking Mode
            report_path = workflow.update_run(
                base_run_id=request.update_from,
                user_query=request.query
            )
        else:
            # Standard Mode
            if request.sources.lower() in ["all", "financial", "social", "tech"]:
                sources_list = [request.sources.lower()]
            else:
                sources_list = [s.strip() for s in request.sources.split(",")]

            report_path = workflow.run(
                query=request.query,
                sources=sources_list,
                wide=request.wide,
                depth=request.depth,
                concurrency=request.concurrency
            )
        
        if report_path:
            jobs[job_id]["status"] = "completed"
            jobs[job_id]["result"] = {
                "report_path": report_path,
                "message": "Analysis completed successfully."
            }
        else:
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = "Workflow finished but returned no report path."
            
    except Exception as e:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)

@app.post("/analyze", response_model=JobResponse)
async def analyze(request: AnalyzeRequest, background_tasks: BackgroundTasks):
    """
    Async analysis endpoint. Returns a job_id immediately.
    """
    job_id = str(uuid.uuid4())
    
    jobs[job_id] = {
        "job_id": job_id,
        "status": "pending",
        "submitted_at": datetime.now().isoformat(),
        "request": request.dict()
    }
    
    # Start background task
    background_tasks.add_task(run_workflow_task, job_id, request, root_dir)
    
    return {
        "job_id": job_id,
        "status": "pending",
        "submitted_at": jobs[job_id]["submitted_at"]
    }

@app.get("/status/{job_id}", response_model=JobStatus)
async def get_status(job_id: str):
    """
    Check the status of a job.
    Status: pending -> running -> completed | failed
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
        
    job = jobs[job_id]
    return {
        "job_id": job_id,
        "status": job["status"],
        "result": job.get("result"),
        "error": job.get("error"),
        "timestamp": datetime.now().isoformat()
    }

if __name__ == "__main__":
    # Use a different port than the dashboard to avoid conflict
    uvicorn.run(app, host="0.0.0.0", port=8001)
