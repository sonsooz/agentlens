"""
AgentLens backend — ingests events from the SDK, stores them in SQLite,
serves a query API for the dashboard, and streams live updates.

Run:
    pip install -r requirements.txt
    uvicorn main:app --host 0.0.0.0 --port 8420
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

DB_PATH = Path(__file__).parent / "agentlens.db"

app = FastAPI(title="AgentLens API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project TEXT NOT NULL,
            run_id TEXT NOT NULL,
            agent TEXT NOT NULL,
            type TEXT NOT NULL,
            step_id TEXT,
            ts REAL NOT NULL,
            data TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_run ON events(run_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project ON events(project)")
    conn.commit()
    conn.close()


init_db()


@app.post("/events")
async def ingest_event(request: Request):
    payload = await request.json()
    conn = get_db()
    conn.execute(
        "INSERT INTO events (project, run_id, agent, type, step_id, ts, data) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            payload.get("project", "default"),
            payload.get("run_id", "unknown"),
            payload.get("agent", "unknown"),
            payload.get("type", "event"),
            payload.get("step_id"),
            payload.get("ts", time.time()),
            json.dumps(payload.get("data", {})),
        ),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/api/projects")
def list_projects():
    conn = get_db()
    rows = conn.execute("SELECT DISTINCT project FROM events ORDER BY project").fetchall()
    conn.close()
    return [r["project"] for r in rows]


@app.get("/api/runs")
def list_runs(project: str = "default"):
    conn = get_db()
    rows = conn.execute(
        """
        SELECT run_id,
               MIN(ts) AS started_at,
               MAX(ts) AS last_activity,
               GROUP_CONCAT(DISTINCT agent) AS agents,
               SUM(CASE WHEN type IN ('error','step_error') THEN 1 ELSE 0 END) AS error_count,
               SUM(CASE WHEN type = 'run_end' THEN 1 ELSE 0 END) AS finished
        FROM events
        WHERE project = ?
        GROUP BY run_id
        ORDER BY started_at DESC
        LIMIT 200
        """,
        (project,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM events WHERE run_id = ? ORDER BY ts ASC", (run_id,)
    ).fetchall()
    conn.close()
    events = []
    for r in rows:
        e = dict(r)
        try:
            e["data"] = json.loads(e["data"]) if e["data"] else {}
        except json.JSONDecodeError:
            e["data"] = {}
        events.append(e)
    return {"run_id": run_id, "events": events}


@app.get("/api/stats")
def stats(project: str = "default"):
    conn = get_db()
    row = conn.execute(
        """
        SELECT
          COUNT(DISTINCT run_id) AS total_runs,
          COUNT(DISTINCT agent) AS total_agents,
          SUM(CASE WHEN type IN ('error','step_error') THEN 1 ELSE 0 END) AS total_errors,
          COUNT(*) AS total_events
        FROM events WHERE project = ?
        """,
        (project,),
    ).fetchone()
    conn.close()
    return dict(row)


# Serve the dashboard static files (built separately in /dashboard)
dashboard_dir = Path(__file__).parent.parent / "dashboard"
if dashboard_dir.exists():
    app.mount("/dashboard", StaticFiles(directory=str(dashboard_dir), html=True), name="dashboard")


@app.get("/")
def root():
    index = dashboard_dir / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"status": "AgentLens backend running", "dashboard": "/dashboard"}
