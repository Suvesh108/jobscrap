import itertools
import json
import os
import random
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup
import httpx

DEFAULT_TIMEOUT = 15
DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

# ponytail: proxy rotation from proxies.txt or PROXY_LIST env; fallback to direct connection
def _load_proxies() -> List[str]:
    env_p = os.getenv("PROXY_LIST", "")
    if env_p:
        return [p.strip() for p in env_p.split(",") if p.strip()]
    file_p = Path(__file__).parent / "proxies.txt"
    if file_p.exists():
        return [line.strip() for line in file_p.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]
    return []

_PROXIES = _load_proxies()
_PROXY_CYCLE = itertools.cycle(_PROXIES) if _PROXIES else None

def get_proxy() -> Optional[str]:
    return next(_PROXY_CYCLE) if _PROXY_CYCLE else None

def get_client(headers: Optional[Dict[str, str]] = None, timeout: int = DEFAULT_TIMEOUT, follow_redirects: bool = True) -> httpx.Client:
    h = dict(headers or {})
    if "User-Agent" not in h:
        h["User-Agent"] = DEFAULT_UA
    proxy = get_proxy()
    # ponytail: polite jitter to prevent rapid-fire IP blocks
    time.sleep(random.uniform(0.3, 0.8))
    return httpx.Client(headers=h, proxy=proxy, timeout=timeout, follow_redirects=follow_redirects)

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

# TIER 1: Instahyre (Direct JSON API)
def scrape_instahyre(query: str = "developer", count: int = 20) -> List[Dict[str, Any]]:
    url = f"https://www.instahyre.com/api/v1/job_search/?count={count}&offset=0"
    jobs = []
    try:
        with get_client() as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json().get("objects", [])
    except Exception as e:
        print(f"[instahyre] fetch error: {e}")
        return []

    now = _now_iso()
    for item in data[:count]:
        emp = item.get("employer", {}) or {}
        public_url = item.get("public_url") or f"https://www.instahyre.com{item.get('resource_uri', '')}"
        desc = " | ".join(filter(None, [
            emp.get("instahyre_note"),
            f"Skills: {', '.join(item.get('keywords', []))}" if item.get("keywords") else None
        ]))
        jobs.append({
            "id": str(uuid.uuid4()),
            "source": "instahyre",
            "source_job_id": f"instahyre_{item.get('id')}",
            "title": item.get("title") or item.get("candidate_title") or "Software Developer",
            "company": emp.get("company_name") or "Unknown Company",
            "location": item.get("locations") or "India",
            "job_type": "fulltime",
            "experience_level": "entry/mid",
            "url": public_url,
            "description": desc,
            "posted_date": item.get("reviewed_at"),
            "scraped_at": now,
            "last_checked_at": None,
            "status": "unchecked",
            "consecutive_fails": 0,
            "dedup_group_id": None
        })
    return jobs

# TIER 1/2: Internshala (Server-rendered HTML)
def scrape_internshala(query: str = "developer", count: int = 20) -> List[Dict[str, Any]]:
    slug = query.strip().replace(" ", "-").lower()
    url = f"https://internshala.com/jobs/{slug}-jobs/"
    jobs = []
    try:
        with get_client() as client:
            resp = client.get(url)
            if resp.status_code != 200:
                return []
            html = resp.text
    except Exception as e:
        print(f"[internshala] fetch error: {e}")
        return []

    soup = BeautifulSoup(html, "html.parser")
    cards = soup.find_all("div", class_=re.compile(r"individual_internship"))
    now = _now_iso()
    for c in cards:
        if len(jobs) >= count:
            break
        link = c.find("a", href=re.compile(r"/job/detail/"))
        if not link:
            continue
        title = link.get_text(strip=True)
        href = "https://internshala.com" + link.get("href", "")
        comp_el = c.find(class_=re.compile(r"company"))
        comp = comp_el.get_text(strip=True).split("\n")[0].strip() if comp_el else "Unknown Company"
        loc_el = c.find(class_=re.compile(r"location"))
        loc = loc_el.get_text(strip=True) if loc_el else "India"
        job_id = href.split("/")[-1]
        jobs.append({
            "id": str(uuid.uuid4()),
            "source": "internshala",
            "source_job_id": f"internshala_{job_id}",
            "title": title or "Software Developer",
            "company": comp,
            "location": loc,
            "job_type": "fulltime",
            "experience_level": "fresher/0-2yr",
            "url": href,
            "description": "",
            "posted_date": None,
            "scraped_at": now,
            "last_checked_at": None,
            "status": "unchecked",
            "consecutive_fails": 0,
            "dedup_group_id": None
        })
    return jobs

# TIER 2: Shine.com (Next.js SSR JSON)
def scrape_shine(query: str = "developer", count: int = 20) -> List[Dict[str, Any]]:
    slug = query.strip().replace(" ", "-").lower()
    url = f"https://www.shine.com/job-search/{slug}-jobs"
    jobs = []
    try:
        with get_client() as client:
            resp = client.get(url)
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, "html.parser")
            tag = soup.find("script", id="__NEXT_DATA__")
            if not tag or not tag.string:
                return []
            data = json.loads(tag.string)
            raw_jobs = data['props']['pageProps']['initialState']['jsrp']['searchresult']['data']['results']
    except Exception as e:
        print(f"[shine] fetch error: {e}")
        return []

    now = _now_iso()
    for item in raw_jobs[:count]:
        loc = item.get("jLoc")
        loc_str = ", ".join(loc) if isinstance(loc, list) else (loc or "India")
        slug_path = item.get("jSlug") or ""
        job_url = f"https://www.shine.com/jobs/{slug_path}" if not slug_path.startswith("http") else slug_path
        desc = BeautifulSoup(item.get("jJD", ""), "html.parser").get_text(strip=True)[:500]
        jobs.append({
            "id": str(uuid.uuid4()),
            "source": "shine",
            "source_job_id": f"shine_{item.get('id')}",
            "title": item.get("jJT") or "Software Developer",
            "company": item.get("jCName") or "Unknown Company",
            "location": loc_str,
            "job_type": "fulltime",
            "experience_level": item.get("jExp", "mid"),
            "url": job_url,
            "description": desc,
            "posted_date": None,
            "scraped_at": now,
            "last_checked_at": None,
            "status": "unchecked",
            "consecutive_fails": 0,
            "dedup_group_id": None
        })
    return jobs

# TIER 2: Freshersworld (Fresher-focused HTML)
def scrape_freshersworld(query: str = "developer", count: int = 20) -> List[Dict[str, Any]]:
    slug = query.strip().replace(" ", "-").lower()
    url = f"https://www.freshersworld.com/jobs/jobsearch/{slug}-jobs"
    jobs = []
    try:
        with get_client() as client:
            resp = client.get(url)
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"[freshersworld] fetch error: {e}")
        return []

    now = _now_iso()
    for a in soup.find_all("a"):
        if len(jobs) >= count:
            break
        if "View & Apply" in a.get_text():
            p = a.find_parent("div")
            while p and not p.find("span", class_="wrap-title"):
                p = p.find_parent("div")
            if not p:
                continue
            title_el = p.find("span", class_="wrap-title")
            comp_el = p.find("h3", class_="latest-jobs-title") or p.find("span", class_="bold_title")
            loc_el = p.find("span", class_="job-location")
            raw_title = title_el.get_text(strip=True) if title_el else "Software Trainee"
            if raw_title.endswith("Less"):
                raw_title = raw_title[:-4].strip()
            href = a.get("href", "")
            job_id = href.split("-")[-1] if "-" in href else href
            jobs.append({
                "id": str(uuid.uuid4()),
                "source": "freshersworld",
                "source_job_id": f"freshers_{job_id}",
                "title": raw_title,
                "company": comp_el.get_text(strip=True) if comp_el else "Unknown Company",
                "location": loc_el.get_text(strip=True) if loc_el else "India",
                "job_type": "fulltime",
                "experience_level": "fresher",
                "url": href,
                "description": "",
                "posted_date": None,
                "scraped_at": now,
                "last_checked_at": None,
                "status": "unchecked",
                "consecutive_fails": 0,
                "dedup_group_id": None
            })
    return jobs

# TIER 2: Apna (Blue-collar / Entry-level HTML)
def scrape_apna(query: str = "developer", count: int = 20) -> List[Dict[str, Any]]:
    url = f"https://apna.co/jobs?location=all-india&text={query}"
    jobs = []
    try:
        with get_client() as client:
            resp = client.get(url)
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, "html.parser")
            links = [a for a in soup.find_all("a") if a.get("href") and "/job/" in a.get("href")][:count]
    except Exception as e:
        print(f"[apna] fetch error: {e}")
        return []

    now = _now_iso()
    for l in links:
        title_el = l.find("h2")
        if not title_el:
            continue
        spans = [s.get_text(strip=True) for s in l.find_all("span") if s.get_text(strip=True)]
        comp = spans[0] if len(spans) > 0 else "Unknown Company"
        loc = spans[1] if len(spans) > 1 else "India"
        href = l.get("href", "")
        job_id = href.split("-")[-1] if "-" in href else href
        jobs.append({
            "id": str(uuid.uuid4()),
            "source": "apna",
            "source_job_id": f"apna_{job_id}",
            "title": title_el.get_text(strip=True),
            "company": comp,
            "location": loc,
            "job_type": "fulltime",
            "experience_level": "entry/fresher",
            "url": f"https://apna.co{href}",
            "description": " | ".join(spans[2:5]),
            "posted_date": None,
            "scraped_at": now,
            "last_checked_at": None,
            "status": "unchecked",
            "consecutive_fails": 0,
            "dedup_group_id": None
        })
    return jobs

# TIER 2: Indeed India (Direct Server-rendered Mobile)
def scrape_indeed(query: str = "developer", count: int = 20) -> List[Dict[str, Any]]:
    url = f"https://in.indeed.com/m/jobs?q={query}&l=India"
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Dest": "document"
    }
    jobs = []
    try:
        with get_client(headers=headers) as client:
            resp = client.get(url)
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, "html.parser")
            links = [a for a in soup.find_all("a") if a.get("href") and "jk=" in a.get("href")]
    except Exception as e:
        print(f"[indeed] fetch error: {e}")
        return []

    seen = set()
    now = _now_iso()
    for l in links:
        if len(jobs) >= count:
            break
        m = re.search(r"jk=([a-zA-Z0-9]+)", l.get("href"))
        if not m:
            continue
        jk = m.group(1)
        if jk in seen:
            continue
        seen.add(jk)
        title = l.get_text(strip=True)
        p = l.find_parent("div", class_=re.compile(r"job_seen_beacon|cardOutline|tapItem")) or l.find_parent("td")
        comp = "Unknown Company"
        loc = "India"
        if p:
            comp_el = p.find("span", {"data-testid": "company-name"}) or p.find(class_=re.compile(r"company"))
            if comp_el:
                comp = comp_el.get_text(strip=True)
            loc_el = p.find("div", {"data-testid": "text-location"}) or p.find(class_=re.compile(r"location"))
            if loc_el:
                loc = loc_el.get_text(strip=True)
        jobs.append({
            "id": str(uuid.uuid4()),
            "source": "indeed",
            "source_job_id": f"indeed_{jk}",
            "title": title or "Software Developer",
            "company": comp,
            "location": loc,
            "job_type": "fulltime",
            "experience_level": "entry/mid",
            "url": f"https://in.indeed.com/viewjob?jk={jk}",
            "description": "",
            "posted_date": None,
            "scraped_at": now,
            "last_checked_at": None,
            "status": "unchecked",
            "consecutive_fails": 0,
            "dedup_group_id": None
        })
    return jobs

# TIER 1/2: Naukri (Native Windows Edge via Playwright, zero extra binary downloads)
def scrape_naukri(query: str = "developer", count: int = 20) -> List[Dict[str, Any]]:
    slug = query.strip().replace(" ", "-").lower()
    url = f"https://www.naukri.com/{slug}-jobs"
    jobs = []
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True, args=["--disable-blink-features=AutomationControlled"])
            context = browser.new_context(user_agent=DEFAULT_UA)
            page = context.new_page()
            page.goto(url, timeout=25000)
            page.wait_for_timeout(4000)
            extracted = page.evaluate("""() => {
                const links = Array.from(document.querySelectorAll('a')).filter(a => a.href.includes('job-listings') && a.innerText.trim().length > 3);
                return links.map(a => {
                    let card = a.parentElement;
                    for (let i = 0; i < 5 && card && card.parentElement; i++) {
                        if (card.querySelector('.comp-name') || card.querySelector('.locWdth')) break;
                        card = card.parentElement;
                    }
                    const comp = card ? card.querySelector('.comp-name') : null;
                    const loc = card ? (card.querySelector('.locWdth') || card.querySelector('.loc-wrap')) : null;
                    const exp = card ? card.querySelector('.expwdth') : null;
                    return {
                        title: a.innerText.trim(),
                        url: a.href,
                        company: comp ? comp.innerText.trim() : 'Unknown Company',
                        location: loc ? loc.innerText.trim() : 'India',
                        experience: exp ? exp.innerText.trim() : '0-5 Yrs'
                    };
                });
            }""")
            browser.close()
            now = _now_iso()
            seen_urls = set()
            for item in extracted:
                if len(jobs) >= count:
                    break
                u = item.get("url", "")
                if u in seen_urls:
                    continue
                seen_urls.add(u)
                job_id = u.split("-")[-1] if "-" in u else str(uuid.uuid4())
                jobs.append({
                    "id": str(uuid.uuid4()),
                    "source": "naukri",
                    "source_job_id": f"naukri_{job_id}",
                    "title": item.get("title") or "Software Developer",
                    "company": item.get("company") or "Unknown Company",
                    "location": item.get("location") or "India",
                    "job_type": "fulltime",
                    "experience_level": item.get("experience") or "0-5 Yrs",
                    "url": u,
                    "description": "",
                    "posted_date": None,
                    "scraped_at": now,
                    "last_checked_at": None,
                    "status": "unchecked",
                    "consecutive_fails": 0,
                    "dedup_group_id": None
                })
    except Exception as e:
        print(f"[naukri] fetch error: {e}")
    return jobs

# TIER 3: LinkedIn (Direct Guest API)
def scrape_linkedin(query: str = "developer", count: int = 20) -> List[Dict[str, Any]]:
    url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={query}&location=India&start=0"
    jobs = []
    try:
        with get_client() as client:
            resp = client.get(url)
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.find_all("li")[:count]
    except Exception as e:
        print(f"[linkedin] fetch error: {e}")
        return []

    now = _now_iso()
    for c in cards:
        title_el = c.find("h3", class_="base-search-card__title")
        comp_el = c.find("h4", class_="base-search-card__subtitle")
        loc_el = c.find("span", class_="job-search-card__location")
        link_el = c.find("a", class_="base-card__full-link")
        if not title_el or not link_el:
            continue
        link = link_el.get("href", "").split("?")[0]
        match = re.search(r"-(\d+)$", link)
        source_id = match.group(1) if match else link
        jobs.append({
            "id": str(uuid.uuid4()),
            "source": "linkedin",
            "source_job_id": f"linkedin_{source_id}",
            "title": title_el.get_text(strip=True),
            "company": comp_el.get_text(strip=True) if comp_el else "Unknown Company",
            "location": loc_el.get_text(strip=True) if loc_el else "India",
            "job_type": "fulltime",
            "experience_level": "mid",
            "url": link,
            "description": "",
            "posted_date": None,
            "scraped_at": now,
            "last_checked_at": None,
            "status": "unchecked",
            "consecutive_fails": 0,
            "dedup_group_id": None
        })
    return jobs

SCRAPERS = {
    "instahyre": scrape_instahyre,
    "naukri": scrape_naukri,
    "internshala": scrape_internshala,
    "shine": scrape_shine,
    "freshersworld": scrape_freshersworld,
    "apna": scrape_apna,
    "indeed": scrape_indeed,
    "linkedin": scrape_linkedin,
}
