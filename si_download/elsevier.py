"""Elsevier SI collector — via Chrome, extracts PII, probes MMC CDN."""

import re
import time
from pathlib import Path


def collect_links(driver, doi: str, paper_dir: Path) -> dict[str, str]:
    """Navigate to Elsevier via DOI redirect, extract PII, probe mmc CDN URLs."""
    import requests as req

    url = f"https://doi.org/{doi}"
    driver.get(url)
    time.sleep(2)

    start = time.time()
    while time.time() - start < 60:
        try:
            title = driver.title.lower()
            if "请稍候" not in title and "just a moment" not in title:
                break
        except Exception:
            pass
        time.sleep(2)

    # Extract PII from URL or page source
    current_url = driver.current_url
    pii_match = re.search(r'/pii/(S\d+)', current_url)
    if not pii_match:
        pii_match = re.search(
            r'["\']pii["\']\s*:\s*["\']([SX]\d+)["\']',
            driver.page_source,
        )
    if not pii_match:
        print("      Could not extract PII from Elsevier page")
        return {}

    pii = pii_match.group(1)
    print(f"      PII: {pii}")

    links: dict[str, str] = {}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    for n in range(1, 11):
        for ext in ("pdf", "doc", "docx"):
            mmc_url = f"https://ars.els-cdn.com/content/image/1-s2.0-{pii}-mmc{n}.{ext}"
            try:
                resp = req.head(mmc_url, headers=headers, timeout=10, allow_redirects=True)
                if resp.status_code == 200:
                    fname = f"1-s2.0-{pii}-mmc{n}.{ext}"
                    if fname not in links:
                        links[mmc_url] = fname
            except Exception:
                pass
    return links
