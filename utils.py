import ipaddress
import logging
import os
import random
import re
import socket
import time
import urllib.parse
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger("jobscrap")

# OWASP A01:2025 SSRF Guard
def is_safe_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        # Block common local hostnames
        if hostname.lower() in ("localhost", "metadata.google.internal", "instance-data"):
            return False
        addr_info = socket.getaddrinfo(hostname, None)
        for _, _, _, _, sockaddr in addr_info:
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
        return True
    except Exception:
        return False

# OWASP A05:2025 Query & Path Sanitizer
def sanitize_slug(query: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9\s-]", "", query.strip())
    slug = re.sub(r"[\s-]+", "-", cleaned).lower()
    return slug or "developer"

# OWASP A09:2025 Proxy Credential Redaction
def redact_credentials(text: str) -> str:
    return re.sub(r"://([^:]+):([^@]+)@", r"://***:***@", str(text))

# Resilient Retry with Exponential Backoff
def retry_call(func: Callable, *args, max_retries: int = 3, base_delay: float = 1.0, **kwargs) -> Any:
    for attempt in range(1, max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if attempt == max_retries:
                logger.error(f"Failed after {max_retries} attempts: {redact_credentials(e)}")
                raise
            sleep_time = base_delay * (2 ** (attempt - 1)) + random.uniform(0.1, 0.5)
            logger.warning(f"Attempt {attempt} failed ({redact_credentials(e)}). Retrying in {sleep_time:.1f}s...")
            time.sleep(sleep_time)

# Salary Normalization (Annual INR min/max)
def parse_salary(text: str) -> Tuple[Optional[int], Optional[int]]:
    if not text:
        return None, None
    clean = text.lower().replace(",", "")
    # Check for Lakhs / LPA
    lakh_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)\s*(?:lakh|lpa)", clean)
    if lakh_match:
        return int(float(lakh_match.group(1)) * 100000), int(float(lakh_match.group(2)) * 100000)
    single_lakh = re.search(r"(\d+(?:\.\d+)?)\s*(?:lakh|lpa)", clean)
    if single_lakh:
        val = int(float(single_lakh.group(1)) * 100000)
        return val, val
    # Monthly/annual rupee range: e.g. ₹20000 - ₹25000
    rupee_matches = re.findall(r"(?:₹|rs\.?)\s*(\d+)", clean)
    if len(rupee_matches) >= 2:
        v1, v2 = int(rupee_matches[0]), int(rupee_matches[1])
        if v1 < 100000: # monthly salary -> convert to annual
            return v1 * 12, v2 * 12
        return v1, v2
    return None, None

# Webhook Alerting (Discord / Slack)
def send_webhook_alert(job: Dict[str, Any], webhook_url: Optional[str] = None):
    url = webhook_url or os.getenv("WEBHOOK_URL")
    if not url:
        return
    try:
        from curl_cffi import requests
        payload = {
            "content": f"🎯 **New High-Match Job Found!**\n**{job['title']}** at **{job['company']}**\n📍 {job['location']} | 💼 {job['source'].upper()}\n🔗 {job['url']}"
        }
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        logger.warning(f"Webhook delivery failed: {e}")
