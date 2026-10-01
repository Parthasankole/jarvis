import sqlite3
from pathlib import Path

# Database file inside your JarvisWorkspace
DB_PATH = Path.home() / "JarvisWorkspace" / "jarvis_memory.db"

def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS memory
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  key TEXT UNIQUE,
                  value TEXT,
                  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

def save_memory(key: str, value: str) -> str:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    key_clean = key.strip().lower()
    c.execute("INSERT OR REPLACE INTO memory (key, value) VALUES (?, ?)", (key_clean, value.strip()))
    conn.commit()
    conn.close()
    return f"Remembered: {key_clean} is {value.strip()}."

def recall_memory(search_term: str) -> str:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    term = f"%{search_term.strip().lower()}%"
    c.execute("SELECT key, value FROM memory WHERE key LIKE ? OR value LIKE ?", (term, term))
    rows = c.fetchall()
    conn.close()
    if not rows:
        return f"No memory found for '{search_term}'."
    results = [f"{r[0]} is {r[1]}" for r in rows]
    return f"From memory: {', '.join(results)}."