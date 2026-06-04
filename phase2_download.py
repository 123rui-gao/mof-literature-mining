"""
Phase 2: Download main paper PDF + Supporting Information from DOI.

Main PDF: uses scansci-pdf (Sci-Hub / OA / publisher)
SI: batch download by publisher (ACS/Wiley/Elsevier via Chrome, RSC via HTTP)

Input:  Phase 1 output CSV (must have "doi" column)
Output: CSV with Main_PDF and SI_Path columns added

Usage:
    python phase2_download.py -i phase1_output.csv -o phase2_output.csv
    python phase2_download.py -i phase1_output.csv --main-only
    python phase2_download.py -i phase1_output.csv --si-only
    python phase2_download.py -i phase1_output.csv --limit 10
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

from loguru import logger

from si_download.batch_downloader import download_all_si, doi_slug, publisher

ROOT = Path(__file__).resolve().parent
PAPERS_DIR = ROOT / "papers"
SI_KEYWORDS = ["si", "suppl", "supporting", "esi", "appendix", "supplementary"]


# ── Main PDF download ──────────────────────────────────────────────────────

def download_main_pdf(doi: str, paper_dir: Path) -> Path | None:
    """Download main paper PDF via scansci-pdf. Returns path or None."""
    paper_pdf = paper_dir / "paper.pdf"
    if paper_pdf.exists() and paper_pdf.stat().st_size > 10000:
        logger.info(f"  Already exists: {paper_pdf}")
        return paper_pdf

    for pdf in paper_dir.glob("*.pdf"):
        if pdf.stat().st_size > 10000:
            if pdf != paper_pdf:
                pdf.rename(paper_pdf)
            return paper_pdf

    paper_dir.mkdir(parents=True, exist_ok=True)

    # Try scansci-pdf Python API
    try:
        from scansci_pdf.sources import download as scansci_download
        result = scansci_download(
            doi,
            output_dir=str(paper_dir),
            scihub_enabled=True,
            use_vpnsci=False,
        )
        if result.get("success") and result.get("file"):
            path = Path(result["file"])
            if path.suffix == ".pdf" and path.stat().st_size > 10000:
                if path.parent != paper_dir:
                    import shutil
                    shutil.copy2(path, paper_pdf)
                elif path != paper_pdf:
                    path.rename(paper_pdf)
                return paper_pdf
    except ImportError:
        logger.debug("scansci_pdf not installed")
    except Exception as e:
        logger.warning(f"scansci-pdf API failed for {doi}: {e}")

    # Check for any downloaded PDF
    for pdf in paper_dir.glob("*.pdf"):
        if pdf.stat().st_size > 10000:
            if pdf != paper_pdf:
                pdf.rename(paper_pdf)
            return paper_pdf

    logger.error(f"  FAILED to download main PDF for {doi}")
    return None


# ── CSV handling ───────────────────────────────────────────────────────────

def _scan_dir(paper_dir: Path) -> tuple[str | None, str]:
    """Return (main_pdf, si_paths_joined)."""
    if not paper_dir.exists():
        return None, ""

    all_pdfs = sorted([
        f for f in paper_dir.iterdir()
        if f.is_file() and f.suffix.lower() == ".pdf" and f.stat().st_size > 5000
    ])

    main_pdf = None
    main_size = 0
    si_files = []

    for f in all_pdfs:
        name_lower = f.name.lower()
        if any(kw in name_lower for kw in SI_KEYWORDS):
            si_files.append(str(f.resolve()))
            continue
        if re.match(r'^[a-z]{1,2}\d[a-z0-9]{5,}(?:\d)?\.pdf$', f.name, re.IGNORECASE):
            si_files.append(str(f.resolve()))
            continue
        if re.match(r'^1-s2\.0-S\d+-mmc\d+\.pdf$', f.name, re.IGNORECASE):
            si_files.append(str(f.resolve()))
            continue
        if main_pdf is None:
            main_pdf = str(f.resolve())
            main_size = f.stat().st_size
        elif abs(f.stat().st_size - main_size) / max(main_size, 1) < 0.05:
            continue
        else:
            si_files.append(str(f.resolve()))

    for f in sorted(paper_dir.iterdir()):
        if not f.is_file() or f.stat().st_size < 5000:
            continue
        if f.suffix.lower() in {".doc", ".docx"}:
            si_files.append(str(f.resolve()))

    return main_pdf, ";".join(si_files)


def update_csv_paths(input_csv: Path, output_csv: Path):
    """Scan papers directory and fill in Main_PDF and SI_Path."""
    rows = []
    with open(input_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        rows = list(reader)

    for col in ["Main_PDF", "SI_Path"]:
        if col not in fieldnames:
            fieldnames.append(col)

    for row in rows:
        doi = row.get("doi", "").strip()
        if doi:
            slug = doi_slug(doi)
            paper_dir = PAPERS_DIR / slug
            if paper_dir.exists():
                main_pdf, si_path = _scan_dir(paper_dir)
                if main_pdf:
                    row["Main_PDF"] = main_pdf
                if si_path:
                    row["SI_Path"] = si_path

    with open(output_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return output_csv


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Phase 2: Download papers by DOI")
    p.add_argument("-i", "--input", required=True, help="Input CSV (Phase 1 output, must have 'doi' column)")
    p.add_argument("-o", "--output", default="phase2_output.csv", help="Output CSV")
    p.add_argument("--limit", type=int, default=0, help="Limit unique DOIs to process")
    p.add_argument("--main-only", action="store_true", help="Only download main PDFs")
    p.add_argument("--si-only", action="store_true", help="Only download SI files")
    p.add_argument("--skip-downloaded", action="store_true", help="Skip DOIs that already have paper.pdf")
    args = p.parse_args()

    # Setup logging
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    logger.add(log_dir / "phase2.log", level="DEBUG", rotation="50 MB", encoding="utf-8")

    # Read CSV
    with open(args.input, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    # Extract unique DOIs
    doi_rows: dict[str, list[dict]] = {}
    for row in rows:
        doi = row.get("doi", "").strip()
        status = row.get("status", "").strip()
        if doi and status != "not_found":
            doi_rows.setdefault(doi, []).append(row)

    unique_dois = sorted(doi_rows.keys())
    logger.info(f"Unique DOIs: {len(unique_dois)} (from {len(rows)} rows)")

    if args.limit:
        unique_dois = unique_dois[:args.limit]
        logger.info(f"Limited to {args.limit} DOIs")

    PAPERS_DIR.mkdir(parents=True, exist_ok=True)

    # ── Main PDFs ────────────────────────────────────────────────────────
    if not args.si_only:
        logger.info(f"\n{'=' * 60}\nPhase 2a: Main PDF download ({len(unique_dois)} DOIs)\n{'=' * 60}")
        success = 0
        for i, doi in enumerate(unique_dois):
            paper_dir = PAPERS_DIR / doi_slug(doi)
            logger.info(f"[{i + 1}/{len(unique_dois)}] {doi}")
            if args.skip_downloaded and (paper_dir / "paper.pdf").exists():
                logger.info("  Skipping (already downloaded)")
                success += 1
                continue
            result = download_main_pdf(doi, paper_dir)
            if result:
                success += 1
        logger.info(f"Main PDF: {success}/{len(unique_dois)} downloaded")

    # ── SI ────────────────────────────────────────────────────────────────
    if not args.main_only:
        logger.info(f"\n{'=' * 60}\nPhase 2b: SI download\n{'=' * 60}")
        download_all_si(unique_dois, PAPERS_DIR)

    # ── Write output CSV ─────────────────────────────────────────────────
    output_path = update_csv_paths(Path(args.input), Path(args.output))
    logger.info(f"\nOutput: {output_path}")


if __name__ == "__main__":
    main()
