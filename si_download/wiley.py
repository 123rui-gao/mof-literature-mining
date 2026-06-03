"""Wiley SI collector — via Chrome (bypasses Cloudflare)."""

import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from selenium.webdriver.common.by import By

from .batch_downloader import SI_EXTENSIONS


def collect_links(driver, doi: str, paper_dir: Path) -> dict[str, str]:
    """Navigate to Wiley article page, expand accordions, collect SI links."""
    url = f"https://onlinelibrary.wiley.com/doi/{doi}"
    driver.get(url)
    time.sleep(2)

    # Wait for Cloudflare
    start = time.time()
    while time.time() - start < 60:
        try:
            title = driver.title.lower()
            if "请稍候" not in title and "just a moment" not in title:
                break
        except Exception:
            pass
        time.sleep(2)

    # Expand accordion sections
    for acc in driver.find_elements(By.CLASS_NAME, "accordion__control"):
        try:
            if acc.get_attribute("aria-expanded") == "false":
                driver.execute_script("arguments[0].click();", acc)
                time.sleep(0.5)
        except Exception:
            pass

    links: dict[str, str] = {}
    for a in driver.find_elements(By.TAG_NAME, "a"):
        try:
            href = (a.get_attribute("href") or "").strip()
            data_href = (a.get_attribute("data-href") or "").strip()
            for h in [href, data_href]:
                if not h:
                    continue
                hl = h.lower()
                if "/downloadsupplement" in hl or "/downloadsuppl" in hl:
                    qs = parse_qs(urlparse(h).query)
                    fname = qs.get("file", [""])[0]
                    if fname:
                        ext = Path(fname).suffix.lower()
                        if ext in SI_EXTENSIONS and ext != ".cif":
                            if fname not in links:
                                links[h] = fname
                elif any(kw in hl for kw in [
                    "/suppinfo/", "/supporting/", "suppl",
                    "supmat", "sup-file", "/supinfo/",
                ]):
                    fname = h.split("/")[-1].split("?")[0]
                    ext = Path(fname).suffix.lower()
                    if ext in SI_EXTENSIONS and ext != ".cif":
                        if fname not in links:
                            links[h] = fname
        except Exception:
            continue
    return links
