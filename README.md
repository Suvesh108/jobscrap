# JobScrap — Ultimate Python Job Scraper & Aggregator

<p align="center">
  <strong>The high-performance, open-source Python Job Scraper & Aggregator for India & Global tech hiring.</strong><br>
  <em>Direct JSON APIs, TLS Fingerprint Bypass, Smart Jaccard Deduplication, and Autonomous Dead-Link Removal.</em>
</p>

<p align="center">
  <a href="https://github.com/Suvesh108/jobscrap/releases/tag/v0.1"><img src="https://img.shields.io/badge/Release-v0.1-blue.svg" alt="Release v0.1" /></a>
  <img src="https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg" alt="Python Version" />
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License" />
  <img src="https://img.shields.io/badge/Portals-9%20Sources-orange.svg" alt="Portals" />
  <img src="https://img.shields.io/badge/Anti--Bot-TLS%20Bypass-purple.svg" alt="TLS Bypass" />
</p>

---

## 📖 About JobScrap

**JobScrap** is the most complete, modern, and autonomous **Python job scraper and aggregator** built to ingest, normalize, and validate job postings from the top hiring platforms without fragile dependencies or expensive commercial APIs.

Unlike generic scrapers that only dump raw un-deduplicated CSVs, **JobScrap** is a self-contained aggregation pipeline that handles the full job lifecycle:
1. **Multi-Source Scraping**: Scrapes 9 major hiring portals with zero third-party scraper wrappers.
2. **TLS Fingerprint Bypass**: Emulates genuine browser TLS signatures (JA3, JA4, cipher suites, HTTP/2 frames) to bypass Cloudflare Turnstile and anti-scraping firewalls.
3. **Cross-Board Jaccard Deduplication**: Detects and links identical job postings across multiple boards using token similarity (`0.75`).
4. **Dead-Link Auto-Purge**: Regularly audits job links with asynchronous `HEAD`/`GET` requests, automatically deleting dead/expired postings after two consecutive checks.
5. **REST API & Autonomous Daemon**: Serves data through a built-in FastAPI backend (`GET /jobs`, `GET /stats`) and runs 24/7 background cron loops.

---

## 🌐 Supported Job Portals & Scraping Methods

| Job Portal | Tier | Scraping Method | Anti-Bot Bypass |
|---|:---:|---|---|
| **Naukri** | Tier 1/2 | Native Windows Edge via Playwright | Bypasses client-side React rendering & reCAPTCHA with zero binary downloads |
| **LinkedIn** | Tier 3 | Public Guest Search API | Direct HTTP, no login credentials required |
| **Indeed India** | Tier 2 | Server-Rendered Mobile Engine | Safari 17 TLS fingerprint bypass via `curl_cffi` |
| **Glassdoor** | Tier 3 | Server-Rendered HTML Scraper | Chrome 124 TLS fingerprint bypass (solves Cloudflare blocks) |
| **Instahyre** | Tier 1 | Direct JSON Search API (`/api/v1/job_search/`) | High-speed direct JSON ingestion |
| **Internshala** | Tier 1/2 | Server-Rendered HTML Scraper | Fresher & internship focus with salary parsing |
| **Shine.com** | Tier 2 | Next.js SSR JSON (`__NEXT_DATA__`) | Structured JSON extraction directly from page payload |
| **Freshersworld** | Tier 2 | Server-Rendered HTML Scraper | Entry-level & graduate job vacancy coverage |
| **Apna** | Tier 2 | Server-Rendered HTML Scraper | Blue-collar & Tier 2/3 city job coverage with salary normalization |

---

## ⚡ JobScrap vs. JobSpy

| Feature | JobSpy | JobScrap (This Project) |
|---|:---:|:---:|
| **India Platform Coverage** | ❌ Poor (Naukri frequently broken; no Instahyre, Internshala, Shine, Apna, Freshersworld) | ✅ **Complete** (All 9 major Indian & global hiring portals) |
| **Anti-Bot TLS Fingerprinting** | ⚠️ Partial (`curl-cffi` on limited sources) | ✅ **Full** (`curl_cffi` Chrome124/Safari17 + Native Edge for React portals) |
| **Cross-Portal Deduplication** | ❌ None (Returns raw duplicates) | ✅ **Built-in** (Token Jaccard similarity `0.75` with candidate pre-filtering) |
| **Dead-Link Removal** | ❌ None (Expired URLs remain in output forever) | ✅ **Autonomous** (Background async worker auto-purging 404/410 links) |
| **Persistence Layer** | ❌ In-memory pandas DataFrame only | ✅ **Server-side SQLite** with WAL mode and conflict upserts |
| **Built-in REST API** | ❌ None | ✅ **FastAPI server** with search, pagination, and export |
| **Autonomous Scheduling** | ❌ None (Requires external wrapper) | ✅ **Built-in asyncio daemon** ([scheduler.py](scheduler.py)) |

---

## 🚀 Quickstart & Installation

### 1. Installation
```bash
# Clone the repository
git clone https://github.com/Suvesh108/jobscrap.git
cd jobscrap

# Install lightweight dependencies
pip install curl_cffi beautifulsoup4 playwright fastapi uvicorn
```

*(Optional: Add HTTP/SOCKS proxies to `proxies.txt` for high-volume distributed scraping)*

### 2. Scrape Jobs
```bash
# Scrape across all 9 supported portals (e.g. 5 jobs per board)
python scraper.py scrape --source all --query "python developer" --count 5

# Scrape from a single specific portal
python scraper.py scrape --source naukri --query "react developer" --count 10
python scraper.py scrape --source linkedin --query "data engineer" --count 10
python scraper.py scrape --source glassdoor --query "backend developer" --count 10
python scraper.py scrape --source instahyre --count 15
```

### 3. Validate Links & Purge Expired Jobs
```bash
# Run asynchronous dead-link verification and purge 404/410 postings
python scraper.py validate --hours 6
```

### 4. Run REST API Server
```bash
# Start FastAPI backend on port 8000
python scraper.py serve --port 8000

# Available Endpoints:
# GET  /jobs?query=python&location=bangalore&min_salary=1000000&limit=50
# GET  /jobs/{id}
# GET  /stats
# POST /scrape?source=all&query=developer&count=10
# POST /validate?stale_hours=6
# GET  /export?format=json|csv
```

### 5. Export Jobs to CSV / JSON
```bash
# Export active database to CSV or JSON
python scraper.py export --format csv --output jobs.csv
python scraper.py export --format json --output jobs.json
```

### 6. Run Autonomous 24/7 Scheduler Daemon
```bash
# Scrapes every 12 hours, validates links every 4 hours automatically
python scheduler.py --scrape-hours 12 --validate-hours 4
```

### 7. Run Verification Test Suite
```bash
# Run internal self-tests (SSRF protection, salary parsing, scalable dedup, DB operations)
python scraper.py test
```

---

## 📊 Canonical Job Schema

Every job record is normalized into this consistent schema:

```json
{
  "id": "c3a64939-5ce5-41be-b697-76b2512f453c",
  "source": "naukri | linkedin | indeed | glassdoor | instahyre | internshala | shine | freshersworld | apna",
  "source_job_id": "naukri_210726911215",
  "title": "Python Backend Developer",
  "company": "Infosys",
  "location": "Bengaluru",
  "job_type": "fulltime",
  "experience_level": "2-5 Yrs",
  "url": "https://www.naukri.com/job-listings-python-backend-developer-infosys-limited-bengaluru-2-to-5-years-210726911215",
  "description": "Skills: Python, Django, REST APIs",
  "posted_date": "2026-09-02T10:00:00Z",
  "scraped_at": "2026-09-03T05:00:00Z",
  "last_checked_at": "2026-09-03T05:10:00Z",
  "status": "live",
  "consecutive_fails": 0,
  "dedup_group_id": "a9840bb8-2a14-4eb9-bfd4-cf3d8495a123",
  "min_salary_inr": 800000,
  "max_salary_inr": 1400000
}
```

---

## 🔒 Security & Privacy (OWASP Top 10:2025)

- **SSRF Prevention (A01:2025)**: Validates destination IPs during link validation to prevent probing private subnets (`10.0.0.0/8`, `192.168.0.0/16`, `127.0.0.0/8`) and cloud metadata endpoints (`169.254.169.254`).
- **Input Sanitization (A05:2025)**: Sanitizes search queries and URL slugs to block path manipulation.
- **Credential Protection (A09:2025)**: Automatically redacts proxy credentials from logs and error messages.
- **SQL Injection Safe**: All queries use parameterized bind variables (`?` / `:key`) with zero string interpolation.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
