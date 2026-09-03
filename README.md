# JobScrap

An autonomous, multi-tier job scraper and aggregator for India-focused hiring platforms. Built from scratch without heavy scraper frameworks or `jobspy`.

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

### 4. Run Autonomous 24/7 Scheduler
```bash
# Scrape every 12 hours, validate links every 4 hours
python scheduler.py --scrape-hours 12 --validate-hours 4
```

### 5. Self-Test Verification
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
