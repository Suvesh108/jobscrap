# JobScrap — Job Aggregator Scraping Architecture

## 1. Goals

- Pull jobs from a wider set of India-focused sources, not just Naukri/Indeed
- Every job link is validated regularly; dead/expired links are auto-removed
- Runs daily (or more often) without manual re-triggering
- Sits on top of your existing stack: Python/FastAPI scraper (port 8000), Node/Express/Puppeteer scraper (port 8001), React/Vite frontend, Jaccard dedup + IndexedDB

---

## 2. Source tiers

Not all sources are equal in cost/reliability. Rank sources by how they're accessed, and prefer higher tiers wherever possible.

### Tier 1 — Direct JSON API (cheapest, most stable, least likely to break)
| Source | Notes |
|---|---|
| **Instahyre** | Its front-end calls a public, unauthenticated JSON endpoint (`GET /api/v1/job_search/`) with no cookies or challenge required — scrape this endpoint directly instead of the HTML page. Tech-focused (metro cities). |
| **Naukri** | Has an internal JSON search API used by its own front-end (found via browser devtools → Network tab while searching). More stable than HTML scraping, but headers/params change occasionally — treat as semi-stable, not guaranteed. |
| **Internshala** | Similar internal API pattern; you're likely already close to this in your Node/Puppeteer scraper. |

### Tier 2 — Server-rendered HTML (moderate effort, moderate stability)
| Source | Notes |
|---|---|
| **Indeed India** | JobSpy already covers this reasonably; watch for Cloudflare Turnstile on high volume. |
| **Foundit** (formerly Monster India) | Mid-management + generalist reach, decent volume for non-tech roles. |
| **Shine.com** | Good supplementary volume, inventory tends to skew older/less fresh — weight it lower in ranking. |
| **Freshersworld** | Entry-level/fresher-focused — high relevance for your target audience (fresher/entry roles), unlimited free postings so volume is high. |
| **TimesJobs** | Generalist, moderate volume. |
| **Hirist** | Tech-focused, senior + mid; part of the iimjobs family. |
| **Cutshort** | AI-matched tech hiring; has a documented REST API + MCP server at their dev docs — check if they expose public search results without auth. |
| **Apna** | Strong in blue-collar/entry-level and Tier-2/3 city roles — good complement to Freshersworld given your fresher focus. |

### Tier 3 — Heavy anti-bot / JS-required (expensive, fragile — deprioritize or use sparingly)
| Source | Notes |
|---|---|
| **LinkedIn** | Already in your Node/Puppeteer scraper — keep it there, it needs a real browser. Rate-limit hard. |
| **Glassdoor** | TLS-fingerprint blocked for most non-browser clients; low ROI unless you already have working Puppeteer logic. |
| **Google Jobs** | Requires JS rendering; consider skipping unless you already have a headless-browser path free. |
| **Wellfound** | Thin India-specific pool, mostly startup/global — low priority for a fresher-focused India app. |

**Recommended near-term additions, in priority order:** Instahyre (cheap win, tech roles) → Freshersworld + Apna (fresher-focused, high volume, aligned with your target audience) → Foundit + Shine (broader generalist coverage) → Hirist/Cutshort (tech, if you want to skew senior later).

---

## 3. Pipeline architecture

```
                    ┌─────────────────────────────────────────┐
                    │              SCHEDULER                  │
                    │   (cron / APScheduler — daily trigger)  │
                    └───────────────┬───────────────────────┘
                                    │
            ┌───────────────────────┼───────────────────────┐
            ▼                       ▼                       ▼
   ┌─────────────────┐   ┌──────────────────┐   ┌──────────────────────┐
   │ Python/FastAPI   │   │ Node/Express      │   │ New: API-tier        │
   │ scraper :8000    │   │ /Puppeteer :8001  │   │ scraper (Instahyre,  │
   │ (JobSpy: Naukri, │   │ (LinkedIn,        │   │ Naukri-JSON, etc.)   │
   │ Indeed, Glassdoor│   │  Internshala)     │   │ lightweight, no      │
   │ + add Foundit,   │   │                   │   │ browser needed       │
   │ Shine, Freshers, │   │                   │   │                      │
   │ Apna via requests│   │                   │   │                      │
   │ /BeautifulSoup)  │   │                   │   │                      │
   └────────┬─────────┘   └─────────┬─────────┘   └──────────┬───────────┘
            │                       │                        │
            └───────────────────────┼────────────────────────┘
                                    ▼
                    ┌─────────────────────────────────┐
                    │      NORMALIZATION LAYER          │
                    │  map every source's fields into   │
                    │  one canonical Job schema (§4)    │
                    └───────────────┬───────────────────┘
                                    ▼
                    ┌─────────────────────────────────┐
                    │      DEDUPLICATION                │
                    │  Jaccard similarity (title+company │
                    │  +location) — you already have this│
                    │  tune threshold per source pair     │
                    └───────────────┬───────────────────┘
                                    ▼
                    ┌─────────────────────────────────┐
                    │      PRIMARY STORE                │
                    │  (server-side DB — see §6 note;   │
                    │   IndexedDB stays as client cache) │
                    └───────────────┬───────────────────┘
                                    │
                          (separate, staggered schedule)
                                    ▼
                    ┌─────────────────────────────────┐
                    │   LINK VALIDATION WORKER           │
                    │  HEAD/GET check on job URLs,       │
                    │  mark dead → soft-delete → purge   │
                    │  (see §5)                          │
                    └───────────────┬───────────────────┘
                                    ▼
                    ┌─────────────────────────────────┐
                    │      FRONTEND (React/Vite)        │
                    │  reads only live, deduped jobs    │
                    └───────────────────────────────────┘
```

Key structural decision: **the scrape job and the link-validation job are two separate scheduled processes.** Don't validate links inline during scraping — it doubles your request volume against sites that are already rate-limiting you, and a source being temporarily slow shouldn't block new jobs from being ingested.

---

## 4. Canonical job schema

Normalize every source into this shape before dedup/storage:

```python
{
    "id": "uuid",                      # generated at normalization time
    "source": "naukri | indeed | linkedin | instahyre | foundit | ...",
    "source_job_id": "string",         # source's own ID, for re-checking
    "title": "string",
    "company": "string",
    "location": "string",
    "job_type": "fulltime | internship | contract | parttime",
    "experience_level": "fresher | 0-2yr | ...",
    "url": "string",                   # canonical apply/detail link
    "description": "string | null",
    "posted_date": "ISO date | null",
    "scraped_at": "ISO datetime",
    "last_checked_at": "ISO datetime", # updated by link-validation worker
    "status": "live | dead | unchecked",
    "dedup_group_id": "uuid | null"    # jobs merged by Jaccard dedup share this
}
```

`status` and `last_checked_at` are the two fields the dead-link system depends on — add these now if they're not already in your schema.

---

## 5. Dead-link auto-removal workflow

```python
# link_validator.py — runs as its own scheduled job, separate from scraping

import httpx
import asyncio
from datetime import datetime, timedelta

CONCURRENCY = 10
STALE_AFTER_HOURS = 6      # only re-check jobs older than this
HARD_DELETE_AFTER_FAILS = 2 # consecutive failures before purge

async def check_one(client: httpx.AsyncClient, job) -> str:
    """Returns 'live', 'dead', or 'unknown' (network issue, not a real 404)."""
    try:
        resp = await client.head(job.url, follow_redirects=True, timeout=8)
        if resp.status_code in (404, 410):
            return "dead"
        if resp.status_code >= 400:
            # some boards (Naukri) 405 on HEAD — retry with GET
            resp = await client.get(job.url, follow_redirects=True, timeout=8)
            if resp.status_code in (404, 410):
                return "dead"
        return "live" if resp.status_code < 400 else "unknown"
    except (httpx.TimeoutException, httpx.ConnectError):
        return "unknown"   # do NOT treat as dead — could be a block, not expiry

async def run_validation_pass(db):
    cutoff = datetime.utcnow() - timedelta(hours=STALE_AFTER_HOURS)
    jobs = db.get_jobs(status__in=["live", "unchecked"], last_checked_at__lt=cutoff)

    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient() as client:
        async def bounded_check(job):
            async with sem:
                result = await check_one(client, job)
                await asyncio.sleep(0.5)  # stay polite, avoid tripping rate limits
                return job, result

        results = await asyncio.gather(*(bounded_check(j) for j in jobs))

    for job, result in results:
        job.last_checked_at = datetime.utcnow()
        if result == "dead":
            job.consecutive_fails = getattr(job, "consecutive_fails", 0) + 1
            if job.consecutive_fails >= HARD_DELETE_AFTER_FAILS:
                db.delete(job)          # confirmed dead twice → purge
            else:
                job.status = "dead"     # flagged, purged next pass if still dead
        elif result == "live":
            job.consecutive_fails = 0
            job.status = "live"
        # "unknown" → leave status as-is, don't punish for a network blip
        db.save(job)
```

Rules baked into this design, and why:

- **HEAD first, GET fallback** — Naukri and a few others reject HEAD with a 405; falling back avoids false dead-flags.
- **Two consecutive failures before deletion** — a single timeout can be a block/network blip, not real expiry. Requiring 2 failures across separate passes (e.g. 6h apart) avoids nuking jobs on a bad network moment.
- **Concurrency capped + small sleep** — validating hundreds of links fast can get *you* rate-limited by the source site, which then looks like everything is "dead." Keep this gentle.
- **Only check jobs past `STALE_AFTER_HOURS`** — no reason to re-check a job that was confirmed live 20 minutes ago.

Schedule this to run every few hours (not every minute) — e.g. 4x/day is enough to keep the list clean without hammering source sites.

---

## 6. Scheduling setup

```python
# scheduler.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

# Full scrape — once daily (or 2-3x if sources allow it)
scheduler.add_job(run_full_scrape, "cron", hour=6, minute=0)

# Link validation — staggered, independent cadence
scheduler.add_job(run_validation_pass, "interval", hours=4)

scheduler.start()
```

If you'd rather not manage a long-running process, this maps cleanly onto:
- **cron** on a VPS, calling two separate scripts
- **GitHub Actions scheduled workflow** (free tier is enough for this volume)
- A lightweight queue (Celery/RQ) if you want retries and visibility later

---

## 7. Storage note

IndexedDB (client-side) is fine as a *cache* for the frontend, but a scheduled backend job needs a **server-side store** (Postgres/SQLite) it can write to independently of any browser being open — the scraper and validator both need to run whether or not the frontend is loaded anywhere. If you don't have this yet, that's the one structural gap to close before the daily-schedule + auto-removal pieces will work end-to-end.

---

## 8. Suggested folder structure

```
jobscrap/
├── scrapers/
│   ├── jobspy_scraper/        # existing FastAPI :8000 — Naukri, Indeed, Glassdoor
│   ├── puppeteer_scraper/     # existing Node :8001 — LinkedIn, Internshala
│   └── api_tier_scraper/      # NEW — Instahyre + any other direct-JSON sources
├── pipeline/
│   ├── normalize.py           # maps each source's raw fields → canonical schema
│   ├── dedup.py                # existing Jaccard logic
│   └── link_validator.py      # NEW — §5
├── scheduler.py                # NEW — APScheduler or cron entry point
├── db/
│   └── models.py               # add status, last_checked_at, consecutive_fails
└── frontend/                   # existing React/Vite/Zustand app
```

---

## 9. Suggested next steps, in order

1. Add `status`, `last_checked_at`, `consecutive_fails` to your job schema/DB.
2. Build `link_validator.py` and run it manually once against your current DB to see how many existing jobs are already dead — that number tells you how bad the current problem is.
3. Wire it into a scheduler (§6) running independently of the scrape job.
4. Add Instahyre (Tier 1, cheapest win) as a new source in a small dedicated scraper module.
5. Add Freshersworld + Apna next, since they're fresher-focused and match your app's target audience.
6. Re-tune your Jaccard threshold once new sources are in — more sources means more near-duplicate titles/companies to catch.
