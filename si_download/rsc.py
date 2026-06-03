"""RSC SI collector — pure HTTP, no Chrome needed."""

import re
from pathlib import Path
from urllib.parse import urljoin

from .batch_downloader import SI_EXTENSIONS


def collect_links(doi: str, paper_dir: Path) -> dict[str, str]:
    """Collect RSC SI links via HTTP."""
    import requests as req

    doi_url = f"https://doi.org/{doi}"
    links: dict[str, str] = {}

    try:
        resp = req.get(doi_url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }, timeout=30, allow_redirects=True)
        if resp.status_code != 200:
            return links

        html = resp.text

        # suppdata URLs
        for m in re.finditer(
            r'https?://[^"\']*suppdata[^"\']*\.(pdf|docx?|doc)[^"\']*',
            html, re.IGNORECASE,
        ):
            url = m.group(0)
            fname = url.split("/")[-1].split("?")[0]
            ext = Path(fname).suffix.lower()
            if ext in SI_EXTENSIONS and ext != ".cif":
                if fname not in links:
                    links[url] = fname

        # Supplementary / ESI links
        for pattern in [
            r'href="([^"]*supplementary[^"]*)"',
            r'href="([^"]*esi[^"]*\.pdf)"',
            r'href="([^"]*c[0-9][a-z0-9]+[0-9]\.pdf)"',
        ]:
            for m in re.finditer(pattern, html, re.IGNORECASE):
                href = m.group(1)
                if not href.startswith("http"):
                    href = urljoin(resp.url, href)
                fname = href.split("/")[-1].split("?")[0]
                ext = Path(fname).suffix.lower()
                if ext in SI_EXTENSIONS and ext != ".cif":
                    if fname not in links:
                        links[href] = fname

        # Constructed suppdata URL
        article_code = doi.split("/")[-1].lower()
        if len(article_code) > 3:
            code_prefix = article_code[:2]
            code_year = article_code[2:3] if len(article_code) > 4 else ""
            supp_url = (
                f"https://www.rsc.org/suppdata/{code_year}/"
                f"{code_prefix}/{article_code}/{article_code}1.pdf"
            )
            try:
                head = req.head(
                    supp_url, timeout=10, allow_redirects=True,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if head.status_code == 200:
                    fname = supp_url.split("/")[-1]
                    if fname not in links:
                        links[supp_url] = fname
            except Exception:
                pass

    except Exception as e:
        print(f"      RSC HTTP error: {e}")

    return links
