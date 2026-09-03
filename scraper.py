import argparse
import asyncio
import re
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Set
import httpx

import db
import scrapers

# ponytail: token-based Jaccard similarity over title, company, location.
def tokenize(job: Dict[str, Any]) -> Set[str]:
    raw = f"{job.get('title', '')} {job.get('company', '')} {job.get('location', '')}"
    return set(re.findall(r"\w+", raw.lower()))

def jaccard_score(set1: Set[str], set2: Set[str]) -> float:
    if not set1 or not set2:
        return 0.0
    return len(set1 & set2) / len(set1 | set2)

def assign_dedup_groups(new_jobs: List[Dict[str, Any]], existing_jobs: List[Dict[str, Any]], threshold: float = 0.75):
    pool = [(j, tokenize(j)) for j in existing_jobs]
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

# Link Validator worker (HEAD first, GET fallback, 2 fails -> purge)
async def check_single_url(client: httpx.AsyncClient, url: str) -> str:
    try:
        r = await client.head(url, follow_redirects=True, timeout=8)
        if r.status_code in (404, 410):
            return "dead"
        if r.status_code >= 400:
            r = await client.get(url, follow_redirects=True, timeout=8)
            if r.status_code in (404, 410):
                return "dead"
        return "live" if r.status_code < 400 else "unknown"
    except (httpx.TimeoutException, httpx.ConnectError):
        return "unknown"

async def run_link_validation(stale_hours: int = 6, concurrency: int = 5):
    stale = db.get_stale_jobs(stale_hours)
    if not stale:
        print("No stale jobs to validate.")
        return

    sem = asyncio.Semaphore(concurrency)
    headers = {"User-Agent": scrapers.DEFAULT_UA}
    async with httpx.AsyncClient(headers=headers) as client:
        async def bounded_check(job):
            async with sem:
                res = await check_single_url(client, job["url"])
                await asyncio.sleep(0.3)
                return job, res

        results = await asyncio.gather(*(bounded_check(j) for j in stale))

    purged, updated = 0, 0
    for job, status in results:
        fails = job.get("consecutive_fails", 0)
        if status == "dead":
            fails += 1
            if fails >= 2:
                db.purge_job(job["id"])
                purged += 1
                continue
            db.update_job_status(job["id"], "dead", fails)
        elif status == "live":
            db.update_job_status(job["id"], "live", 0)
        else:
            db.update_job_status(job["id"], job["status"], fails)
        updated += 1

    print(f"Validation complete: {updated} updated, {purged} purged.")

def run_pipeline(source: str = "all", query: str = "developer", count: int = 10):
    db.init_db()
    existing = db.get_all_jobs()
    targets = scrapers.SCRAPERS.items() if source == "all" else [(source, scrapers.SCRAPERS[source])]

    all_scraped = []
    for name, func in targets:
        print(f"Scraping [{name}] (query='{query}', limit={count})...")
        try:
            items = func(query, count)
            print(f"  -> fetched {len(items)} jobs from {name}")
            all_scraped.extend(items)
        except Exception as e:
            print(f"  -> failed {name}: {e}")

    assign_dedup_groups(all_scraped, existing)
    for j in all_scraped:
        db.upsert_job(j)
    print(f"Total ingested this run: {len(all_scraped)}. Total jobs in database: {len(db.get_all_jobs())}")

def run_self_test():
    # ponytail: runnable check fails if core dedup or DB breaks
    test_db = db.DB_PATH.parent / "test_jobs.db"
    test_db.unlink(missing_ok=True)
    db.init_db(test_db)
    j1 = {"id": "1", "source": "test", "source_job_id": "s1", "title": "Software Engineer", "company": "Acme", "location": "Bangalore", "job_type": "fulltime", "experience_level": "fresher", "url": "https://example.com/1", "description": "", "posted_date": None, "scraped_at": "2026-09-03T00:00:00", "last_checked_at": None, "status": "unchecked", "consecutive_fails": 0, "dedup_group_id": None}
    j2 = {"id": "2", "source": "test", "source_job_id": "s2", "title": "Software Engineer", "company": "Acme", "location": "Bangalore", "job_type": "fulltime", "experience_level": "fresher", "url": "https://example.com/2", "description": "", "posted_date": None, "scraped_at": "2026-09-03T00:00:00", "last_checked_at": None, "status": "unchecked", "consecutive_fails": 0, "dedup_group_id": None}
    assign_dedup_groups([j1, j2], [])
    assert j1["dedup_group_id"] == j2["dedup_group_id"], "Dedup group mismatch for identical jobs"
    db.upsert_job(j1, test_db)
    assert len(db.get_all_jobs(test_db)) == 1
    db.update_job_status(j1["id"], "dead", 2, test_db)
    db.purge_job(j1["id"], test_db)
    assert len(db.get_all_jobs(test_db)) == 0
    test_db.unlink(missing_ok=True)
    print("Self-test passed.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="JobScrap Scraper & Validator")
    parser.add_argument("cmd", choices=["scrape", "validate", "run", "stats", "test"], default="run", nargs="?")
    parser.add_argument("--source", default="all", choices=["all"] + list(scrapers.SCRAPERS.keys()), help="Scraper source to run")
    parser.add_argument("--query", default="developer", help="Job search keyword")
    parser.add_argument("--count", type=int, default=10, help="Number of jobs to scrape per source")
    parser.add_argument("--hours", type=int, default=0, help="Stale threshold in hours for validation")
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
    elif args.cmd == "test":
        run_self_test()
