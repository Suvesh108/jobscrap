import contextlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(__file__).parent / "jobs.db"

# ponytail: stdlib sqlite3 with WAL mode, auto-migration for salary fields, safe parameterized queries
@contextlib.contextmanager
def get_db(db_path: Path = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
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
            dedup_group_id TEXT,
            min_salary_inr INTEGER,
            max_salary_inr INTEGER
        );
        """)
        # Auto-migration for existing databases
        existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
        if "min_salary_inr" not in existing_cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN min_salary_inr INTEGER;")
        if "max_salary_inr" not in existing_cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN max_salary_inr INTEGER;")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_dedup ON jobs(dedup_group_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_salary ON jobs(min_salary_inr);")

def upsert_job(job: Dict[str, Any], db_path: Path = DB_PATH):
    with get_db(db_path) as conn:
        conn.execute("""
        INSERT INTO jobs (
            id, source, source_job_id, title, company, location,
            job_type, experience_level, url, description, posted_date,
            scraped_at, last_checked_at, status, consecutive_fails, dedup_group_id,
            min_salary_inr, max_salary_inr
        ) VALUES (
            :id, :source, :source_job_id, :title, :company, :location,
            :job_type, :experience_level, :url, :description, :posted_date,
            :scraped_at, :last_checked_at, :status, :consecutive_fails, :dedup_group_id,
            :min_salary_inr, :max_salary_inr
        )
        ON CONFLICT(source_job_id) DO UPDATE SET
            title=excluded.title,
            company=excluded.company,
            location=excluded.location,
            url=excluded.url,
            description=excluded.description,
            min_salary_inr=COALESCE(excluded.min_salary_inr, jobs.min_salary_inr),
            max_salary_inr=COALESCE(excluded.max_salary_inr, jobs.max_salary_inr),
            dedup_group_id=COALESCE(jobs.dedup_group_id, excluded.dedup_group_id);
        """, job)

def get_all_jobs(limit: Optional[int] = None, db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    query = "SELECT * FROM jobs ORDER BY scraped_at DESC"
    params = ()
    if limit is not None:
        query += " LIMIT ?"
        params = (limit,)
    with get_db(db_path) as conn:
        cur = conn.execute(query, params)
        return [dict(row) for row in cur.fetchall()]

def search_jobs(
    query: Optional[str] = None,
    location: Optional[str] = None,
    source: Optional[str] = None,
    min_salary: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db_path: Path = DB_PATH
) -> List[Dict[str, Any]]:
    conditions = []
    params = []
    if query:
        conditions.append("(title LIKE ? OR description LIKE ?)")
        params.extend([f"%{query}%", f"%{query}%"])
    if location:
        conditions.append("location LIKE ?")
        params.append(f"%{location}%")
    if source:
        conditions.append("source = ?")
        params.append(source)
    if min_salary is not None:
        conditions.append("min_salary_inr >= ?")
        params.append(min_salary)
    if status:
        conditions.append("status = ?")
        params.append(status)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"SELECT * FROM jobs {where_clause} ORDER BY scraped_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_db(db_path) as conn:
        cur = conn.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]

def get_candidates_for_dedup(companies: List[str], recent_limit: int = 500, db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    # ponytail: prune pairwise scan by loading jobs matching target companies + most recent pool
    with get_db(db_path) as conn:
        if companies:
            placeholders = ",".join("?" for _ in companies)
            sql = f"""
            SELECT * FROM jobs 
            WHERE company IN ({placeholders})
            UNION
            SELECT * FROM (SELECT * FROM jobs ORDER BY scraped_at DESC LIMIT ?)
            """
            cur = conn.execute(sql, (*companies, recent_limit))
        else:
            cur = conn.execute("SELECT * FROM jobs ORDER BY scraped_at DESC LIMIT ?", (recent_limit,))
        return [dict(row) for row in cur.fetchall()]

def get_stale_jobs(stale_hours: int = 6, limit: int = 100, db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    with get_db(db_path) as conn:
        cur = conn.execute("""
        SELECT * FROM jobs 
        WHERE status != 'dead' 
          AND (last_checked_at IS NULL OR datetime(last_checked_at) <= datetime('now', '-' || ? || ' hours'))
        LIMIT ?
        """, (stale_hours, limit))
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
