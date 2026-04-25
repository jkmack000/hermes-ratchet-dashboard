"""
Hermes Ratchet Dashboard Plugin - Backend
A FastAPI backend plugin that watches an auto-optimization workspace (Git repo)
and streams experiment telemetry to the frontend.
"""

import asyncio
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

router = APIRouter(prefix="/ratchet")

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class Experiment(BaseModel):
    id: str                    # commit hash (short)
    timestamp: str             # ISO format
    score: float
    score_delta: float = 0.0
    status: str                # "improved" | "reverted" | "baseline"
    message: str = ""          # commit message
    branch: str = "main"
    author: str = ""
    duration_ms: int = 0

class RatchetState(BaseModel):
    workspace: str = ""
    running: bool = False
    best_score: float = float("inf")
    best_commit: str = ""
    total_experiments: int = 0
    start_time: str = ""
    current_epoch: int = 0
    log_tail: list[str] = []

class ConfigUpdate(BaseModel):
    workspace: str

# ---------------------------------------------------------------------------
# Global mutable state (per-process, simple for hackathon)
# ---------------------------------------------------------------------------

STATE = RatchetState()
EXPERIMENTS: list[Experiment] = []
LOCK = asyncio.Lock()

# Default workspace — can be overridden via POST /config
DEFAULT_WORKSPACE = os.environ.get("RATCHET_WORKSPACE", str(Path.home() / "auto-research"))
STATE.workspace = DEFAULT_WORKSPACE

# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _run_git(args: list[str], cwd: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git failed: {result.stderr}")
    return result.stdout.strip()

def parse_score_from_message(msg: str) -> Optional[float]:
    # Accepts: "score:1.234", "ratchet:up score:0.5", "best=3.14", etc.
    patterns = [
        r"score[:=]([-+]?\d+\.?\d*)",
        r"best[:=]([-+]?\d+\.?\d*)",
        r"loss[:=]([-+]?\d+\.?\d*)",
    ]
    for pat in patterns:
        m = re.search(pat, msg, re.IGNORECASE)
        if m:
            return float(m.group(1))
    return None

def parse_score_from_file(workspace: str) -> Optional[float]:
    candidates = ["score.txt", "best_score.txt", "experiments.json"]
    for fname in candidates:
        fpath = Path(workspace) / fname
        if not fpath.exists():
            continue
        try:
            if fname.endswith(".json"):
                data = json.loads(fpath.read_text())
                if isinstance(data, dict):
                    return float(data.get("best_score", data.get("score", 0)))
                if isinstance(data, list) and data:
                    return float(data[-1].get("score", 0))
            else:
                text = fpath.read_text().strip().splitlines()[0]
                return float(text)
        except Exception:
            continue
    return None

def fetch_git_history(workspace: str) -> list[Experiment]:
    if not (Path(workspace) / ".git").exists():
        return []

    log_format = "%H|%ci|%s|%an"
    raw = _run_git(
        ["log", "--all", f"--format={log_format}", "--date=iso"],
        cwd=workspace,
    )

    experiments: list[Experiment] = []
    best = float("inf")

    for line in raw.splitlines():
        parts = line.split("|", 3)
        if len(parts) < 4:
            continue
        commit_hash, ts_str, msg, author = parts
        score = parse_score_from_message(msg)
        if score is None:
            score = parse_score_from_file(workspace) or 0.0

        delta = score - best if best != float("inf") else 0.0
        status = "baseline" if best == float("inf") else ("improved" if score < best else "reverted")
        if score < best:
            best = score

        experiments.append(
            Experiment(
                id=commit_hash[:8],
                timestamp=ts_str,
                score=score,
                score_delta=round(delta, 6),
                status=status,
                message=msg,
                author=author,
            )
        )

    return list(reversed(experiments))  # oldest first

# ---------------------------------------------------------------------------
# Background watcher task
# ---------------------------------------------------------------------------

async def _watcher_loop():
    """Poll the workspace every 2 seconds for git changes."""
    last_head = ""
    while True:
        await asyncio.sleep(2)
        ws = STATE.workspace
        if not ws or not (Path(ws) / ".git").exists():
            continue
        try:
            head = _run_git(["rev-parse", "HEAD"], cwd=ws)
            if head == last_head:
                continue
            last_head = head
            exps = fetch_git_history(ws)
            async with LOCK:
                global EXPERIMENTS
                EXPERIMENTS = exps
                if exps:
                    best = min(exps, key=lambda e: e.score)
                    STATE.best_score = best.score
                    STATE.best_commit = best.id
                    STATE.total_experiments = len(exps)
                STATE.running = True  # inferred from activity
                # Simple log tail — git log -5
                log_raw = _run_git(["log", "-5", "--oneline"], cwd=ws)
                STATE.log_tail = log_raw.splitlines()
        except Exception:
            continue

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.on_event("startup")
async def startup_event():
    asyncio.create_task(_watcher_loop())
    # Bootstrap history if workspace exists
    if STATE.workspace and (Path(STATE.workspace) / ".git").exists():
        try:
            exps = fetch_git_history(STATE.workspace)
            async with LOCK:
                global EXPERIMENTS
                EXPERIMENTS = exps
                if exps:
                    best = min(exps, key=lambda e: e.score)
                    STATE.best_score = best.score
                    STATE.best_commit = best.id
                    STATE.total_experiments = len(exps)
        except Exception:
            pass

@router.get("/info")
async def info():
    async with LOCK:
        return STATE.model_dump()

@router.get("/experiments")
async def experiments():
    async with LOCK:
        return [e.model_dump() for e in EXPERIMENTS]

@router.get("/experiments/latest")
async def latest():
    async with LOCK:
        if not EXPERIMENTS:
            raise HTTPException(status_code=404, detail="No experiments found")
        return EXPERIMENTS[-1].model_dump()

@router.get("/sse")
async def sse(request: Request):
    async def event_stream() -> AsyncGenerator[str, None]:
        last_len = -1
        while True:
            await asyncio.sleep(1)
            if await request.is_disconnected():
                break
            async with LOCK:
                current_len = len(EXPERIMENTS)
                payload = {
                    "state": STATE.model_dump(),
                    "latest": EXPERIMENTS[-1].model_dump() if EXPERIMENTS else None,
                    "count": current_len,
                }
            if current_len != last_len:
                last_len = current_len
                yield f"data: {json.dumps(payload)}\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream")

@router.post("/config")
async def update_config(cfg: ConfigUpdate):
    ws = Path(cfg.workspace).expanduser().resolve()
    if not (ws / ".git").exists():
        raise HTTPException(status_code=400, detail="Path is not a git repository")
    async with LOCK:
        STATE.workspace = str(ws)
        global EXPERIMENTS
        EXPERIMENTS = fetch_git_history(str(ws))
    return {"workspace": str(ws), "experiments_loaded": len(EXPERIMENTS)}

# Serve the dashboard HTML at the router root too
_dash_html = Path(__file__).with_name("..").resolve() / "dashboard.html"
@router.get("/", response_class=HTMLResponse)
async def dashboard():
    if _dash_html.exists():
        return _dash_html.read_text(encoding="utf-8")
    return HTMLResponse("<h1>Ratchet Plugin</h1><p>dashboard.html not found</p>")

# ---------------------------------------------------------------------------
# Standalone test harness  (uvicorn backend.ratchet:app --reload --port 8765)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI(title="Ratchet Dashboard Plugin")
    app.include_router(router, prefix="/api/plugins")

    @app.get("/", response_class=HTMLResponse)
    async def root():
        return """<!doctype html>
<html><head><title>Ratchet Plugin</title></head>
<body><h1>Ratchet Dashboard Plugin</h1>
<p>Mount this router in your Hermes Agent dashboard backend.</p>
<ul>
<li><a href="/api/plugins/ratchet/info">/api/plugins/ratchet/info</a></li>
<li><a href="/api/plugins/ratchet/experiments">/api/plugins/ratchet/experiments</a></li>
</ul>
</body></html>"""

    uvicorn.run(app, host="0.0.0.0", port=8765)
