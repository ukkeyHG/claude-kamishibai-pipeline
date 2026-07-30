from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import os
import sys
import json
import shutil
import re
from pathlib import Path

# Add project root to path so we can import orchestrator
sys.path.append(str(Path(__file__).parent.parent))
from orchestrator.state import delete_episode_from_db
from orchestrator.config import DB_PATH
import sqlite3

app = FastAPI()

EPISODES_DIR = Path("episodes")

# HTMLなどの静的ファイルを配信する設定
app.mount("/static", StaticFiles(directory="src/static"), name="static")

@app.get("/")
def read_root():
    # index.htmlを直接返す
    index_path = Path("src/static/index.html")
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"), status_code=200)
    return HTMLResponse(content="<h1>Dashboard UI not found</h1>", status_code=404)

@app.get("/api/episodes")
def list_episodes():
    if not EPISODES_DIR.exists():
        return []
    
    episodes = []
    for d in sorted(os.listdir(EPISODES_DIR)):
        episode_path = EPISODES_DIR / d
        if episode_path.is_dir():
            log_path = episode_path / "status.log.jsonl"
            status = "Waiting"
            total_tokens = 0
            
            # 最新のステータスと合計トークン数を取得
            if log_path.exists():
                lines = log_path.read_text(encoding="utf-8").strip().split("\n")
                if lines and lines[0]:
                    try:
                        for line in lines:
                            if not line.strip(): continue
                            data = json.loads(line)
                            status = data.get("phase", status)
                            
                            # トークン数の集計
                            if "tokens" in data:
                                total_tokens += data["tokens"].get("in", 0) + data["tokens"].get("out", 0)
                    except Exception as e:
                        print(f"Error parsing log {log_path}: {e}")
                        
            episodes.append({
                "id": d,
                "status": status,
                "total_tokens": total_tokens
            })
    return episodes

PHASES_CONFIG = [
    {"id": "phase_1", "name": "1. Design", "matcher": "design"},
    {"id": "phase_2", "name": "2. Narration", "matcher": "narration"},
    {"id": "phase_3", "name": "3. Image Prompts", "matcher": "image_prompt"},
    {"id": "phase_4", "name": "4. Video Prompts", "matcher": "video_prompt"},
    {"id": "phase_5", "name": "5. BGM Prompts", "matcher": "bgm"},
    {"id": "phase_6", "name": "6. YouTube", "matcher": "youtube"}
]

def get_db_state(episode_slug: str) -> dict | None:
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        episode = conn.execute("SELECT id, status FROM episodes WHERE episode_slug = ?", (episode_slug,)).fetchone()
        if not episode:
            return None
        steps = conn.execute("SELECT step_name, status, retry_count, started_at, completed_at, tokens_in, tokens_out, active_agent FROM steps WHERE episode_id = ?", (episode["id"],)).fetchall()
        return {
            "status": episode["status"],
            "steps": {s["step_name"]: dict(s) for s in steps}
        }
    finally:
        conn.close()

def parse_pipeline_state(db_state: dict | None) -> dict:
    from datetime import datetime, timezone, timedelta
    
    def format_jst(iso_str: str) -> str | None:
        if not iso_str: return None
        try:
            if not iso_str.endswith("Z") and "+" not in iso_str:
                iso_str += "+00:00"
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            jst = timezone(timedelta(hours=9))
            return dt.astimezone(jst).strftime("%H:%M:%S")
        except Exception:
            return iso_str.split("T")[1][:8] if "T" in iso_str else iso_str

    pipeline_state = {}
    for p in PHASES_CONFIG:
        pipeline_state[p["matcher"]] = {
            "status": "Pending", "iter": "-", "base_iter": 0, "fallback_iter": 1, "attempt": "-", 
            "tokens": 0, "agent": "-", "startTime": None, "endTime": None
        }

    if not db_state or "steps" not in db_state:
        return pipeline_state
        
    db_steps = db_state["steps"]
    
    for p in PHASES_CONFIG:
        matcher = p["matcher"]
        gen_step = db_steps.get(matcher)
        rev_step = db_steps.get(f"{matcher}_review")
        
        state = pipeline_state[matcher]
        
        if not gen_step:
            continue
            
        # 1. Determine Status & Iteration
        if gen_step["status"] == "completed":
            if rev_step:
                if rev_step["status"] == "completed":
                    state["status"] = "Completed"
                else:
                    state["status"] = "Running"
                state["iter"] = rev_step["retry_count"] + 1
            else:
                state["status"] = "Running"
                state["iter"] = 1
        else:
            if gen_step["status"] in ["running", "pending"]:
                state["status"] = "Running"
            elif gen_step["status"] in ["failed", "aborted"]:
                state["status"] = "Failed"
            state["iter"] = gen_step["retry_count"] + 1

        # 2. Map Time, Agent, and Tokens
        if gen_step.get("started_at"):
            state["startTime"] = format_jst(gen_step["started_at"])
            
        if rev_step and rev_step["status"] == "completed" and rev_step.get("completed_at"):
            state["endTime"] = format_jst(rev_step["completed_at"])
        elif gen_step["status"] == "completed" and gen_step.get("completed_at"):
            state["endTime"] = format_jst(gen_step["completed_at"])
            
        total_in = (gen_step.get("tokens_in") or 0) + (rev_step.get("tokens_in") or 0 if rev_step else 0)
        total_out = (gen_step.get("tokens_out") or 0) + (rev_step.get("tokens_out") or 0 if rev_step else 0)
        if total_in > 0 or total_out > 0:
            state["tokens"] = total_in + total_out
            
        active_step = rev_step if (rev_step and rev_step["status"] in ["running", "pending"]) else gen_step
        agent_raw = active_step.get("active_agent", "")
        if agent_raw:
            state["agent"] = "Reviewer" if "reviewer" in agent_raw else ("Generator" if "generator" in agent_raw else agent_raw)
            
    return pipeline_state

@app.get("/api/episodes/{episode_id}")
def get_episode_details(episode_id: str):
    episode_path = EPISODES_DIR / episode_id
    if not episode_path.exists() or not episode_path.is_dir():
        raise HTTPException(status_code=404, detail="Episode not found")
        
    log_path = episode_path / "status.log.jsonl"
    review_path = episode_path / "review_history.md"
    
    logs = []
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").strip().split("\n"):
            if line.strip():
                try:
                    logs.append(json.loads(line))
                except:
                    pass
                    
    review_history = ""
    if review_path.exists():
        review_history = review_path.read_text(encoding="utf-8")
        
    db_state = get_db_state(episode_id)
    pipeline_state = parse_pipeline_state(db_state)
    
    # Generate raw text log
    raw_log_text = ""
    for log in logs:
        ts = log.get("ts", "")
        time_str = ts.split("T")[1][:8] if "T" in ts else ts
        agent = log.get("agent", "")
        phase = log.get("phase", "")
        msg = log.get("message", "")
        raw_log_text += f"[{time_str}] [{agent}] {phase} : {msg}\n"
        
    return {
        "id": episode_id,
        "pipeline_state": pipeline_state,
        "raw_log_text": raw_log_text,
        "review_history": review_history
    }

@app.delete("/api/episodes/{episode_id}")
def delete_episode(episode_id: str):
    # 1. Delete from SQLite DB
    try:
        delete_episode_from_db(episode_id)
    except Exception as e:
        print(f"Failed to delete from DB: {e}")
        # Continue to try deleting files even if DB fails

    # 2. Delete from file system
    episode_path = EPISODES_DIR / episode_id
    if episode_path.exists() and episode_path.is_dir():
        try:
            shutil.rmtree(episode_path)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete directory: {str(e)}")
            
    return {"status": "success", "message": f"Deleted {episode_id}"}

if __name__ == "__main__":
    import uvicorn
    # uvicorn src.dashboard_server:app --reload --host 0.0.0.0 --port 8000
    uvicorn.run("dashboard_server:app", host="0.0.0.0", port=8000, reload=True, app_dir="src")
