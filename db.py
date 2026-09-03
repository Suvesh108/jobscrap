import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(__file__).parent / "jobs.db"

import contextlib

# ponytail: stdlib sqlite3, zero dependencies, WAL mode for concurrent read/write
@contextlib.contextmanager
def get_db(db_path: Path = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db(db_path: Path = DB_PATH):
    with get_db(db_path) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            source_job_id TEXT UNIQUE,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            location TEXT,
            job_type TEXT,
            experience_level TEXT,
            url TEXT NOT NULL,
            description TEXT,
            posted_date TEXT,
            scraped_at TEXT NOT NULL,
            last_checked_at TEXT,
            status TEXT DEFAULT 'unchecked',
            consecutive_fails INTEGER DEFAULT 0,
            dedup_group_id TEXT
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_dedup ON jobs(dedup_group_id);")

def upsert_job(job: Dict[str, Any], db_path: Path = DB_PATH):
    with get_db(db_path) as conn:
        conn.execute("""
        INSERT INTO jobs (
            id, source, source_job_id, title, company, location,
            job_type, experience_level, url, description, posted_date,
            scraped_at, last_checked_at, status, consecutive_fails, dedup_group_id
        ) VALUES (
            :id, :source, :source_job_id, :title, :company, :location,
            :job_type, :experience_level, :url, :description, :posted_date,
            :scraped_at, :last_checked_at, :status, :consecutive_fails, :dedup_group_id
        )
        ON CONFLICT(source_job_id) DO UPDATE SET
            title=excluded.title,
            company=excluded.company,
            location=excluded.location,
            url=excluded.url,
            description=excluded.description,
            dedup_group_id=COALESCE(jobs.dedup_group_id, excluded.dedup_group_id);
        """, job)

def get_all_jobs(db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    with get_db(db_path) as conn:
        cur = conn.execute("SELECT * FROM jobs ORDER BY scraped_at DESC")
        return [dict(row) for row in cur.fetchall()]

def get_stale_jobs(stale_hours: int = 6, db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    with get_db(db_path) as conn:
        cur = conn.execute("""
        SELECT * FROM jobs 
        WHERE status != 'dead' 
          AND (last_checked_at IS NULL OR datetime(last_checked_at) <= datetime('now', '-' || ? || ' hours'))
        """, (stale_hours,))
        return [dict(row) for row in cur.fetchall()]

def update_job_status(job_id: str, status: str, consecutive_fails: int, db_path: Path = DB_PATH):
    now = datetime.now(timezone.utc).isoformat()
    with get_db(db_path) as conn:
        conn.execute("""
        UPDATE jobs 
        SET status = ?, consecutive_fails = ?, last_checked_at = ?
        WHERE id = ?
        """, (status, consecutive_fails, now, job_id))

def purge_job(job_id: str, db_path: Path = DB_PATH):
    with get_db(db_path) as conn:
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
