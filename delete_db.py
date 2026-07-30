import sqlite3
import os

db_path = 'orchestrator/pipeline.db'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM episodes WHERE episode_slug LIKE '%徳島%'")
    conn.commit()
    conn.close()
    print("Deleted ep05 from DB")
