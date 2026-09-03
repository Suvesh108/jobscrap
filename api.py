import csv
import io
import json
from typing import Optional
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

import db
import scraper
import scrapers

app = FastAPI(title="JobScrap API", description="Autonomous India Job Aggregator REST API", version="1.0.0")

# Security: CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup_event():
    db.init_db()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/stats")
def get_stats():
    jobs = db.get_all_jobs()
    live = sum(1 for j in jobs if j["status"] == "live")
    dead = sum(1 for j in jobs if j["status"] == "dead")
    unchecked = len(jobs) - live - dead
    by_src = {}
    for j in jobs:
        by_src[j["source"]] = by_src.get(j["source"], 0) + 1
    return {
        "total_jobs": len(jobs),
        "live": live,
        "dead": dead,
        "unchecked": unchecked,
        "sources": by_src
    }

@app.get("/search")
def search_frontend_compatible(
    query: Optional[str] = None,
    location: Optional[str] = None,
    sources: Optional[str] = None,
    source: Optional[str] = None,
    results: int = Query(25, ge=1, le=100)
):
    # Frontend passes: /search?query=...&location=...&sources=internshala&results=25
    src = sources or source
    target_src = src.lower().strip() if src and src.lower().strip() != "all" else None
    
    # 1. Search DB for matching live jobs with query
    jobs = db.search_jobs(
        query=query,
        location=location,
        source=target_src,
        status="live",
        limit=results
    )
    
    # 2. If no jobs match query in DB, try on-demand live scrape from portal
    if not jobs and target_src and target_src in scrapers.SCRAPERS:
        try:
            fresh = scrapers.SCRAPERS[target_src](query=query or "developer", count=min(results, 10))
            if fresh:
                scraper.assign_dedup_groups(fresh)
                for j in fresh:
                    db.upsert_job(j)
                jobs = fresh
        except Exception as e:
            pass

    # 3. If still empty, return recent live jobs from that source so frontend ALWAYS gets genuine links
    if not jobs and target_src:
        jobs = db.search_jobs(source=target_src, limit=results)

    # 4. If target_src wasn't specified, return general recent jobs
    if not jobs:
        jobs = db.search_jobs(limit=results)

    out = []
    for j in jobs:
        sal = ""
        if j.get("min_salary_inr") and j.get("max_salary_inr"):
            sal = f"₹{j['min_salary_inr']:,} - ₹{j['max_salary_inr']:,}"
        out.append({
            "title": j["title"],
            "company": j["company"],
            "location": j.get("location") or "India",
            "salary": sal,
            "url": j["url"],
            "source": j["source"],
            "postedDate": j.get("posted_date") or j.get("scraped_at", "")[:10],
            "description": j.get("description") or ""
        })
    return out

@app.get("/jobs")
def get_jobs(
    query: Optional[str] = None,
    location: Optional[str] = None,
    source: Optional[str] = None,
    min_salary: Optional[int] = None,
    status: Optional[str] = Query(None, description="live | dead | unchecked"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0)
):
    results = db.search_jobs(
        query=query,
        location=location,
        source=source,
        min_salary=min_salary,
        status=status,
        limit=limit,
        offset=offset
    )
    return {"count": len(results), "offset": offset, "limit": limit, "jobs": results}

@app.get("/jobs/{job_id}")
def get_job_by_id(job_id: str):
    with db.get_db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Job not found")
        return dict(row)

@app.post("/scrape")
def trigger_scrape(
    background_tasks: BackgroundTasks,
    source: str = "all",
    query: str = "developer",
    count: int = Query(10, ge=1, le=50)
):
    background_tasks.add_task(scraper.run_pipeline, source=source, query=query, count=count)
    return {"message": f"Scrape task queued for source='{source}', query='{query}', count={count}."}

@app.post("/validate")
def trigger_validate(background_tasks: BackgroundTasks, stale_hours: int = 6):
    background_tasks.add_task(scraper.run_link_validation, stale_hours=stale_hours)
    return {"message": f"Validation task queued for stale_hours={stale_hours}."}

@app.get("/export")
def export_jobs(format: str = Query("json", pattern="^(json|csv)$"), status: Optional[str] = "live"):
    jobs = db.search_jobs(status=status, limit=10000, offset=0)
    if format == "csv":
        output = io.StringIO()
        if jobs:
            writer = csv.DictWriter(output, fieldnames=list(jobs[0].keys()))
            writer.writeheader()
            writer.writerows(jobs)
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=jobs.csv"}
        )
    return JSONResponse(content=jobs)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
