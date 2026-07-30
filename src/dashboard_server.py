from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import os
import json
from pathlib import Path

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
        
    return {
        "id": episode_id,
        "logs": logs,
        "review_history": review_history
    }

if __name__ == "__main__":
    import uvicorn
    # uvicorn src.dashboard_server:app --reload --host 0.0.0.0 --port 8000
    uvicorn.run("dashboard_server:app", host="0.0.0.0", port=8000, reload=True, app_dir="src")
