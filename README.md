# JobScrap

<p align="center">
  <strong>Autonomous India Job Aggregator, TLS Bypass Scraper & Deduplication Pipeline</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Release-v0.1-blue.svg" alt="Release v0.1" />
  <img src="https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg" alt="Python Version" />
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License" />
  <img src="https://img.shields.io/badge/Sources-9%20Platforms-orange.svg" alt="Sources" />
</p>

---

## 📖 About

**JobScrap** is a self-healing, multi-tier job scraper and aggregator built from scratch specifically for the Indian hiring market. Unlike generic scrapers (like `JobSpy`) that only return raw in-memory dataframes for US boards, JobScrap is an end-to-end autonomous pipeline:

- **9 Indian Platforms**: Aggregates tech, fresher, and entry-level jobs across Instahyre, Naukri, Internshala, Shine, Freshersworld, Apna, Indeed India, Glassdoor, and LinkedIn.
- **TLS Fingerprint Bypass**: Emulates browser TLS handshakes (JA3, JA4, cipher suites, HTTP/2 frames) via `curl_cffi` to glide past Cloudflare Turnstile and bot filters.
- **Autonomous Link Lifecycle**: Includes an independent async validation worker with a 2-strike purge rule that automatically detects and wipes expired/dead links.
- **Smart Deduplication**: Uses token-based Jaccard similarity thresholding (`0.75`) with candidate pre-filtering to prevent cross-board duplicate clutter.
- **Developer First**: Features a persistent SQLite store (WAL mode), FastAPI REST server (`GET /jobs`, `GET /stats`), CSV/JSON export utility, and 24/7 background scheduler daemon.

---

## 🚀 Release v0.1 Highlights

- ⚡ **9 Core Scrapers**: Built from scratch with zero dependency on `jobspy` or Selenium.
- 🛡️ **OWASP Top 10 Hardening**: Built-in SSRF validation guard, path sanitization, and proxy credential masking.
- 💰 **Salary Normalization**: Automatic parsing of LPA, Lakhs, and monthly rupee amounts into integer min/max fields.
- 🌐 **Built-in REST API**: FastAPI server exposing search, pagination, and trigger endpoints for frontend consumption.
- 🔄 **Autonomous Daemon**: Decoupled scraping and link validation loops running 24/7 via standard `asyncio`.

---

## Supported Sources

| Source | Tier | Access Method |
|---|---|---|
| **Instahyre** | Tier 1 | Direct JSON API (`/api/v1/job_search/`) |
| **Internshala** | Tier 1/2 | Server-rendered HTML scraper |
| **Shine.com** | Tier 2 | Next.js SSR JSON (`__NEXT_DATA__`) |
| **Freshersworld** | Tier 2 | Entry-level / fresher HTML parser |
| **Apna** | Tier 2 | Blue-collar / fresher HTML parser |
| **Indeed India** | Tier 2 | Direct mobile SSR scraper (Safari17 TLS bypass) |
| **Naukri** | Tier 1/2 | Native Windows Edge via Playwright (zero extra binary downloads) |
| **Glassdoor** | Tier 3 | Direct HTML scraper (Chrome124 TLS bypass) |
| **LinkedIn** | Tier 3 | Public guest search API |

## Core Features

- **TLS Fingerprint Bypass**: Integrates `curl_cffi` browser impersonation (`chrome124`, `safari17_0`) across scrapers and link validation to bypass Cloudflare, JA3/JA4 fingerprinting, and HTTP/2 bot detection.
- **Jaccard Deduplication**: Token-based Jaccard similarity thresholding (`0.75`) on Title + Company + Location to group cross-board duplicates.
- **Dead-Link Auto-Purge**: Independent validation worker that sends `HEAD` requests (with `GET` fallback). Two consecutive failures automatically purges dead links.
- **Proxy Rotation & Polite Jitter**: Reads from `proxies.txt` or `PROXY_LIST` environment variable with randomized jitter delays between requests.
- **Autonomous Scheduler Daemon**: Independent non-blocking asyncio loops for periodic scraping and link validation passes.
- **Zero Heavy ORM**: Lightweight standard library `sqlite3` storage with WAL mode enabled.

## Setup

```bash
# Clone the repository
git clone https://github.com/Suvesh108/jobscrap.git
cd jobscrap

# Install requirements
pip install httpx beautifulsoup4 playwright
```

*(Optional: Add proxies to `proxies.txt` if high volume scraping is needed)*

## Usage

### 1. Scrape Jobs
```bash
# Scrape across all 8 sources
python scraper.py scrape --source all --query "developer" --count 5

# Scrape a specific source
python scraper.py scrape --source instahyre --count 10
python scraper.py scrape --source naukri --count 10
python scraper.py scrape --source indeed --count 10
```

### 2. Validate Links & Purge Dead Postings
```bash
# Check all stale jobs and purge expired postings
python scraper.py validate --hours 6
```

### 3. Database Statistics
```bash
# View aggregated breakdown of live, dead, and unchecked jobs
python scraper.py stats
```

### 4. REST API Server (FastAPI)
```bash
# Start backend REST API server on port 8000
python scraper.py serve --port 8000

# Endpoints:
# GET  /jobs?query=python&location=bangalore&min_salary=1000000&limit=50
# GET  /jobs/{id}
# GET  /stats
# POST /scrape?source=all&query=developer&count=10
# POST /validate?stale_hours=6
# GET  /export?format=json|csv
```

### 5. Export Data to JSON / CSV
```bash
python scraper.py export --format json --output jobs.json
python scraper.py export --format csv --output jobs.csv
```

### 6. Run Autonomous 24/7 Scheduler Daemon
```bash
# Scrape every 12 hours, validate links every 4 hours
python scheduler.py --scrape-hours 12 --validate-hours 4
```

### 7. Self-Test Verification (Security & Dedup Checks)
```bash
# Run internal assertion test suite
python scraper.py test
```

## Schema

Normalized canonical job record:
```json
{
  "id": "uuid",
  "source": "instahyre | naukri | indeed | linkedin | shine | apna | freshersworld | internshala",
  "source_job_id": "string",
  "title": "string",
  "company": "string",
  "location": "string",
  "job_type": "fulltime | internship | contract | parttime",
  "experience_level": "string",
  "url": "string",
  "description": "string",
  "posted_date": "ISO date | null",
  "scraped_at": "ISO datetime",
  "last_checked_at": "ISO datetime | null",
  "status": "live | dead | unchecked",
  "consecutive_fails": 0,
  "dedup_group_id": "uuid"
}
```
