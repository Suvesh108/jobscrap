import argparse
import asyncio
import csv
import json
import logging
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set
from curl_cffi.requests import AsyncSession

import db
import scrapers
import utils

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("jobscrap")

# ponytail: token-based Jaccard similarity over title, company, location.
def tokenize(job: Dict[str, Any]) -> Set[str]:
    raw = f"{job.get('title', '')} {job.get('company', '')} {job.get('location', '')}"
    return set(re.findall(r"\w+", raw.lower()))

def jaccard_score(set1: Set[str], set2: Set[str]) -> float:
    if not set1 or not set2:
        return 0.0
    return len(set1 & set2) / len(set1 | set2)

# ponytail: candidate pre-filtering prevents O(N*M) memory bottleneck
def assign_dedup_groups(new_jobs: List[Dict[str, Any]], db_path: Path = db.DB_PATH, threshold: float = 0.75):
    companies = list({j.get("company", "").strip() for j in new_jobs if j.get("company")})
    existing_candidates = db.get_candidates_for_dedup(companies=companies, recent_limit=500, db_path=db_path)
    pool = [(j, tokenize(j)) for j in existing_candidates]

    for job in new_jobs:
        tokens = tokenize(job)
        matched_group = None
        for cand, cand_tokens in pool:
            if jaccard_score(tokens, cand_tokens) >= threshold:
                matched_group = cand.get("dedup_group_id") or cand.get("id")
                cand["dedup_group_id"] = matched_group
                break
        job["dedup_group_id"] = matched_group or str(uuid.uuid4())
        pool.append((job, tokens))

def is_dead_redirect(original_url: str, final_url: str, content_snippet: str = "") -> bool:
    orig = original_url.lower()
    final = final_url.lower()
    
    # 1. Naukri soft-404: redirects to search with expJD=true or away from /job-listings
    if "naukri.com" in orig:
        if "expjd=true" in final or "/job-listings" not in final:
            return True
            
    # 2. Indeed soft-404: redirects away from viewjob
    if "indeed.com" in orig:
        if "viewjob" not in final or "from=expired" in final:
            return True
            
    # 3. Internshala soft-404: redirects to /jobs/ or /internships/ list
    if "internshala.com" in orig:
        if "/job/detail/" not in final:
            return True
            
    # 4. Instahyre soft-404: redirects away from /job-
    if "instahyre.com" in orig:
        if "/job-" not in final:
            return True
            
    # 5. Shine soft-404: redirects away from /jobs/
    if "shine.com" in orig:
        if "/jobs/" not in final:
            return True
            
    # 6. Freshersworld soft-404: redirects to category or home
    if "freshersworld.com" in orig:
        if "/jobs/" not in final or "category" in final:
            return True

    # 7. Page content expiration text
    snippet_lower = content_snippet.lower()
    if "job you are looking for is expired" in snippet_lower or "no longer accepting applications" in snippet_lower:
        return True
            
    return False

# OWASP A01:2025 SSRF Guarded Link Validator worker with Soft-404 detection
async def check_single_url(session: AsyncSession, url: str) -> str:
    # SSRF Protection: Reject private/internal/cloud-metadata addresses before requesting
    if not utils.is_safe_url(url):
        logger.warning(f"Blocked unsafe/SSRF URL check: {url}")
        return "dead"
    try:
        r = await session.get(url, allow_redirects=True, timeout=12)
        if r.status_code in (404, 410):
            return "dead"
        final_url = str(r.url)
        snippet = r.text[:2000] if r.text else ""
        if is_dead_redirect(url, final_url, snippet):
            logger.info(f"Detected expired/soft-404 link: {url} -> {final_url}")
            return "dead"
        return "live" if r.status_code < 400 else "unknown"
    except Exception:
        return "unknown"

async def run_link_validation(stale_hours: int = 6, concurrency: int = 5, db_path: Path = db.DB_PATH):
    stale = db.get_stale_jobs(stale_hours, limit=200, db_path=db_path)
    if not stale:
        logger.info("No stale jobs to validate.")
        return

    sem = asyncio.Semaphore(concurrency)
    headers = {"User-Agent": scrapers.DEFAULT_UA}
    proxy = scrapers.get_proxy()
    proxies = {"http": proxy, "https": proxy} if proxy else None

    async with AsyncSession(headers=headers, proxies=proxies, impersonate=scrapers.DEFAULT_IMPERSONATE) as session:
        async def bounded_check(job):
            async with sem:
                res = await check_single_url(session, job["url"])
                await asyncio.sleep(0.3)
                return job, res

        results = await asyncio.gather(*(bounded_check(j) for j in stale))

    purged, updated = 0, 0
    for job, status in results:
        fails = job.get("consecutive_fails", 0)
        if status == "dead":
            fails += 1
            if fails >= 2:
                db.purge_job(job["id"], db_path)
                purged += 1
                continue
            db.update_job_status(job["id"], "dead", fails, db_path)
        elif status == "live":
            db.update_job_status(job["id"], "live", 0, db_path)
        else:
            db.update_job_status(job["id"], job["status"], fails, db_path)
        updated += 1

    logger.info(f"Validation complete: {updated} updated, {purged} purged.")

def run_pipeline(source: str = "all", query: str = "developer", count: int = 10, db_path: Path = db.DB_PATH):
    db.init_db(db_path)
    targets = scrapers.SCRAPERS.items() if source == "all" else [(source, scrapers.SCRAPERS[source])]

    all_scraped = []
    for name, func in targets:
        logger.info(f"Scraping [{name}] (query='{query}', limit={count})...")
        try:
            items = func(query, count)
            logger.info(f"  -> fetched {len(items)} jobs from {name}")
            all_scraped.extend(items)
        except Exception as e:
            logger.error(f"  -> failed {name}: {utils.redact_credentials(e)}")

    assign_dedup_groups(all_scraped, db_path=db_path)
    for j in all_scraped:
        db.upsert_job(j, db_path)
        utils.send_webhook_alert(j)

    total_in_db = len(db.get_all_jobs(db_path=db_path))
    logger.info(f"Total ingested this run: {len(all_scraped)}. Total jobs in database: {total_in_db}")

def export_data(format_type: str = "json", output_file: Optional[str] = None):
    db.init_db()
    jobs = db.get_all_jobs()
    if format_type == "csv":
        out = output_file or "jobs_export.csv"
        with open(out, "w", newline="", encoding="utf-8") as f:
            if jobs:
                writer = csv.DictWriter(f, fieldnames=list(jobs[0].keys()))
                writer.writeheader()
                writer.writerows(jobs)
        print(f"Exported {len(jobs)} jobs to {out}")
    else:
        out = output_file or "jobs_export.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(jobs, f, indent=2, ensure_ascii=False)
        print(f"Exported {len(jobs)} jobs to {out}")

def run_self_test():
    # ponytail: self-test runnable check
    test_db = db.DB_PATH.parent / "test_jobs.db"
    test_db.unlink(missing_ok=True)
    db.init_db(test_db)

    # 1. Test SSRF Guard
    assert not utils.is_safe_url("http://127.0.0.1:8000"), "SSRF failed to block loopback"
    assert not utils.is_safe_url("http://169.254.169.254/latest/meta-data"), "SSRF failed to block cloud metadata"
    assert utils.is_safe_url("https://google.com"), "SSRF blocked valid public URL"

    # 2. Test Salary Normalization
    min_sal, max_sal = utils.parse_salary("Rs 14 - 26 Lakh/Yr")
    assert min_sal == 1400000 and max_sal == 2600000, "Salary Lakh parser failed"

    # 3. Test Jaccard Dedup & Scalable Candidate Pre-filtering
    j1 = {"id": "1", "source": "test", "source_job_id": "s1", "title": "Software Engineer", "company": "Acme", "location": "Bangalore", "job_type": "fulltime", "experience_level": "fresher", "url": "https://example.com/1", "description": "", "posted_date": None, "scraped_at": "2026-09-03T00:00:00", "last_checked_at": None, "status": "unchecked", "consecutive_fails": 0, "dedup_group_id": None, "min_salary_inr": min_sal, "max_salary_inr": max_sal}
    j2 = {"id": "2", "source": "test", "source_job_id": "s2", "title": "Software Engineer", "company": "Acme", "location": "Bangalore", "job_type": "fulltime", "experience_level": "fresher", "url": "https://example.com/2", "description": "", "posted_date": None, "scraped_at": "2026-09-03T00:00:00", "last_checked_at": None, "status": "unchecked", "consecutive_fails": 0, "dedup_group_id": None, "min_salary_inr": min_sal, "max_salary_inr": max_sal}
    assign_dedup_groups([j1, j2], db_path=test_db)
    assert j1["dedup_group_id"] == j2["dedup_group_id"], "Dedup group mismatch for identical jobs"

    # 4. Test Upsert, Search, and Purge
    db.upsert_job(j1, test_db)
    assert len(db.search_jobs(query="Software", min_salary=1000000, db_path=test_db)) == 1
    db.update_job_status(j1["id"], "dead", 2, test_db)
    db.purge_job(j1["id"], test_db)
    assert len(db.get_all_jobs(db_path=test_db)) == 0

    test_db.unlink(missing_ok=True)
    print("Self-test passed: SSRF guard, salary parsing, scalable dedup, and DB operations verified.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="JobScrap Scraper & Validator")
    parser.add_argument("cmd", choices=["scrape", "validate", "run", "stats", "export", "serve", "test"], default="run", nargs="?")
    parser.add_argument("--source", default="all", choices=["all"] + list(scrapers.SCRAPERS.keys()), help="Scraper source to run")
    parser.add_argument("--query", default="developer", help="Job search keyword")
    parser.add_argument("--count", type=int, default=10, help="Number of jobs to scrape per source")
    parser.add_argument("--hours", type=int, default=0, help="Stale threshold in hours for validation")
    parser.add_argument("--format", choices=["json", "csv"], default="json", help="Export format")
    parser.add_argument("--output", help="Output file path for export")
    parser.add_argument("--port", type=int, default=8000, help="Port for REST API server")
    args = parser.parse_args()

    db.init_db()
    if args.cmd == "scrape":
        run_pipeline(source=args.source, query=args.query, count=args.count)
    elif args.cmd == "validate":
        asyncio.run(run_link_validation(stale_hours=args.hours))
    elif args.cmd == "run":
        run_pipeline(source=args.source, query=args.query, count=args.count)
        asyncio.run(run_link_validation(stale_hours=args.hours))
    elif args.cmd == "stats":
        jobs = db.get_all_jobs()
        live = sum(1 for j in jobs if j['status'] == 'live')
        dead = sum(1 for j in jobs if j['status'] == 'dead')
        unchecked = len(jobs) - live - dead
        by_src = {}
        for j in jobs:
            by_src[j['source']] = by_src.get(j['source'], 0) + 1
        print(f"Total: {len(jobs)} | Live: {live} | Dead: {dead} | Unchecked: {unchecked}")
        print("By source:", by_src)
    elif args.cmd == "export":
        export_data(format_type=args.format, output_file=args.output)
    elif args.cmd == "serve":
        import uvicorn
        from api import app
        uvicorn.run(app, host="0.0.0.0", port=args.port)
    elif args.cmd == "test":
        run_self_test()
