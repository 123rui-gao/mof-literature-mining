"""ACS SI collector — via Chrome (bypasses Cloudflare)."""

import time
from pathlib import Path

from selenium.webdriver.common.by import By


def collect_links(driver, doi: str, paper_dir: Path) -> dict[str, str]:
    """Navigate to ACS article page, collect suppl_file links."""
    url = f"https://pubs.acs.org/doi/{doi}"
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

    links: dict[str, str] = {}
    for a in driver.find_elements(By.TAG_NAME, "a"):
        try:
            href = (a.get_attribute("href") or "").strip()
            if any(kw in href for kw in ["/suppl_file/", "/supplementary/", "/si/"]):
                fname = href.split("/")[-1].split("?")[0]
                if fname.lower().endswith(".cif"):
                    continue
                if fname not in links:
                    links[href] = fname
        except Exception:
            continue
    return links
