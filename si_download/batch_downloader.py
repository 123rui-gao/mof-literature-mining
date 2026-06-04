"""
Batch SI downloader — reuses one Chrome session per publisher.
Groups DOIs by publisher, processes all of same type without restarting Chrome.

Supported publishers:
  - ACS    (Chrome — bypasses Cloudflare)
  - Wiley  (Chrome — bypasses Cloudflare)
  - Elsevier (Chrome — PII extraction + MMC CDN)
  - RSC    (Pure HTTP — no Chrome needed)
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
from pathlib import Path

# Must clear proxy env vars before importing undetected_chromedriver —
# Sangfor NDIS driver intercepts all localhost HTTP traffic otherwise
for key in list(os.environ.keys()):
    if "proxy" in key.lower():
        del os.environ[key]

from . import acs, rsc, wiley, elsevier as elsevier_mod

CHROME_BIN = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def publisher(doi: str) -> str:
    """Detect publisher from DOI prefix."""
    d = doi.lower()
    if "10.1021/" in d: return "acs"
    if "10.1039/" in d: return "rsc"
    if "10.1002/" in d: return "wiley"
    if "10.1016/" in d: return "elsevier"
    return "other"


def doi_slug(doi: str) -> str:
    return doi.replace("/", "_")


def download_si_files(links: dict[str, str], output_dir: Path, chrome_driver=None) -> int:
    """Download SI files. Uses Chrome XHR if driver available, else requests."""
    import base64
    import json
    import requests as req

    ok = skip = fail = 0

    for url, fname in links.items():
        target = output_dir / fname
        if target.exists() and target.stat().st_size > 1000:
            skip += 1
            continue

        if chrome_driver:
            js = """
            async function xhrDownload(url) {
                return new Promise((resolve) => {
                    const xhr = new XMLHttpRequest();
                    xhr.open('GET', url, true);
                    xhr.responseType = 'arraybuffer';
                    xhr.onload = function() {
                        if (xhr.status === 200) {
                            const arr = new Uint8Array(xhr.response);
                            let binary = '';
                            for (let i = 0; i < arr.byteLength; i++) {
                                binary += String.fromCharCode(arr[i]);
                            }
                            resolve(JSON.stringify({ok: true, size: arr.byteLength, data: btoa(binary)}));
                        } else {
                            resolve(JSON.stringify({ok: false, status: xhr.status}));
                        }
                    };
                    xhr.onerror = function() {
                        resolve(JSON.stringify({ok: false, error: 'Network error'}));
                    };
                    xhr.send();
                });
            }
            return xhrDownload(arguments[0]);
            """
            result = chrome_driver.execute_script(js, url)
            parsed = json.loads(result)
            if parsed.get("ok") and parsed.get("size", 0) > 1000:
                data = base64.b64decode(parsed["data"])
                with open(target, "wb") as f:
                    f.write(data)
                ok += 1
            else:
                fail += 1
        else:
            try:
                r = req.get(url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }, timeout=60)
                if r.status_code == 200 and len(r.content) > 1000:
                    with open(target, "wb") as f:
                        f.write(r.content)
                    ok += 1
                else:
                    fail += 1
            except Exception:
                fail += 1

    if ok + skip + fail > 0:
        print(f"      SI files: {ok} OK, {skip} skip, {fail} fail")
    return ok + skip


def _launch_chrome(output_dir: Path):
    """Launch undetected Chrome with temp profile — no persistent profile conflicts."""
    import undetected_chromedriver as uc

    tmp_profile = tempfile.mkdtemp(prefix="chrome_si_")

    options = uc.ChromeOptions()
    options.binary_location = CHROME_BIN
    options.add_argument(f"--user-data-dir={tmp_profile}")
    options.add_argument("--window-size=1280,800")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("prefs", {
        "download.default_directory": str(output_dir),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
        "plugins.always_open_pdf_externally": True,
    })
    driver = uc.Chrome(options=options, version_main=148)
    driver._tmp_profile = tmp_profile
    return driver


def _wait_for_page(driver, timeout=60):
    """Wait for Cloudflare challenge to complete."""
    time.sleep(2)
    start = time.time()
    while time.time() - start < timeout:
        try:
            title = driver.title.lower()
            if "请稍候" not in title and "just a moment" not in title:
                return True
        except Exception:
            pass
        elapsed = int(time.time() - start)
        if elapsed % 15 == 0:
            print(f"      Waiting Cloudflare... ({elapsed}s)")
        time.sleep(2)
    return False


def _has_si_files(paper_dir: Path) -> bool:
    """Check if paper_dir already has SI files."""
    if not paper_dir.exists():
        return False
    return any(
        re.match(r".*(_si_|_sm_|supp|mmc|_SI_|_SM_)", f.name)
        for f in paper_dir.iterdir() if f.is_file()
    )


def _chrome_session(dois: list[str], collect_fn, publisher_name: str,
                    papers_dir: Path) -> int:
    """Process DOIs with a single Chrome session. Auto-reconnects on failure."""
    driver = None
    total_processed = 0

    def ensure_driver():
        nonlocal driver
        if driver is None:
            driver = _launch_chrome(papers_dir)

    i = 0
    while i < len(dois):
        doi = dois[i]
        tag = f"[{i + 1}/{len(dois)}]"
        paper_dir = papers_dir / doi_slug(doi)
        paper_dir.mkdir(parents=True, exist_ok=True)

        if _has_si_files(paper_dir):
            existing = [
                f.name for f in paper_dir.iterdir()
                if re.match(r".*(_si_|_sm_|supp|mmc|_SI_|_SM_)", f.name)
            ]
            print(f"  {tag} {doi}  (skip — {len(existing)} SI already present)")
            total_processed += 1
            i += 1
            continue

        try:
            if driver is None:
                ensure_driver()
            else:
                try:
                    driver.current_url
                except Exception:
                    print(f"  Chrome disconnected, reconnecting...")
                    driver = None
                    ensure_driver()

            links = collect_fn(driver, doi, paper_dir)
            if links:
                for url, fname in links.items():
                    print(f"        [{len(links)}] {fname}")
                download_si_files(links, paper_dir, driver)
            else:
                print(f"        No SI links found")
            total_processed += 1
            i += 1
            time.sleep(5)  # Delay between DOIs to avoid rate limiting

        except Exception as e:
            print(f"  {tag} {doi}  ERROR: {e}")
            try:
                tmp = getattr(driver, '_tmp_profile', None)
                driver.quit()
                if tmp:
                    shutil.rmtree(tmp, ignore_errors=True)
            except Exception:
                pass
            driver = None
            time.sleep(2)
            total_processed += 1
            i += 1

    if driver:
        try:
            tmp = getattr(driver, '_tmp_profile', None)
            driver.quit()
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass
    print(f"  Chrome closed\n")
    return total_processed


def _http_session(dois: list[str], collect_fn, publisher_name: str,
                  papers_dir: Path) -> int:
    """Process DOIs via HTTP (no Chrome)."""
    total_processed = 0
    for i, doi in enumerate(dois):
        tag = f"[{i + 1}/{len(dois)}]"
        paper_dir = papers_dir / doi_slug(doi)
        paper_dir.mkdir(parents=True, exist_ok=True)

        if _has_si_files(paper_dir):
            print(f"  {tag} {doi}  (skip — SI already present)")
            total_processed += 1
            continue

        try:
            links = collect_fn(doi, paper_dir)
            if links:
                for url, fname in links.items():
                    print(f"        [{len(links)}] {fname}")
                download_si_files(links, paper_dir)
            else:
                print(f"        No SI files found")
        except Exception as e:
            print(f"  {tag} {doi}  ERROR: {e}")
        total_processed += 1
    print()
    return total_processed


def download_all_si(dois: list[str], papers_dir: Path) -> int:
    """Download SI for all DOIs, grouped by publisher. Returns total processed."""
    from collections import defaultdict

    groups = defaultdict(list)
    for doi in dois:
        pub = publisher(doi)
        if pub != "other":
            groups[pub].append(doi)

    print("DOIs by publisher:")
    for pub, dl in sorted(groups.items()):
        print(f"  {pub}: {len(dl)}")
    print()

    total = 0

    if groups.get("acs"):
        print(f"{'=' * 60}\nACS: {len(groups['acs'])} DOIs (Chrome, shared session)\n{'=' * 60}")
        total += _chrome_session(groups["acs"], acs.collect_links, "ACS", papers_dir)

    if groups.get("wiley"):
        print(f"{'=' * 60}\nWiley: {len(groups['wiley'])} DOIs (Chrome, shared session)\n{'=' * 60}")
        total += _chrome_session(groups["wiley"], wiley.collect_links, "Wiley", papers_dir)

    if groups.get("elsevier"):
        print(f"{'=' * 60}\nElsevier: {len(groups['elsevier'])} DOIs (Chrome, shared session)\n{'=' * 60}")
        total += _chrome_session(groups["elsevier"], elsevier_mod.collect_links, "Elsevier", papers_dir)

    if groups.get("rsc"):
        print(f"{'=' * 60}\nRSC: {len(groups['rsc'])} DOIs (HTTP, no Chrome)\n{'=' * 60}")
        total += _http_session(groups["rsc"], rsc.collect_links, "RSC", papers_dir)

    return total
