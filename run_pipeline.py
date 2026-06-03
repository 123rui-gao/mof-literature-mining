"""
Unified CLI for the 3-phase MOF literature mining pipeline.

Phase 1: CSD API lookup — refcode/SI filename -> DOI + unit cell (a,b,c)
Phase 2: Paper download — DOI -> main PDF (scansci-pdf) + SI (batch by publisher)
Phase 3: LLM extraction — PDF text -> DeepSeek -> BET/synthesis/crystal match

Usage:
  # Run all three phases
  python run_pipeline.py --all -i compounds.csv

  # Run individual phases
  python run_pipeline.py --phase1 -i compounds.csv -o phase1_out.csv
  python run_pipeline.py --phase2 -i phase1_out.csv -o phase2_out.csv
  python run_pipeline.py --phase3 -i phase2_out.csv -o final.xlsx

  # Phase 2: main-only or SI-only
  python run_pipeline.py --phase2 -i phase1_out.csv --main-only
  python run_pipeline.py --phase2 -i phase1_out.csv --si-only

  # Phase 3: limit processing
  python run_pipeline.py --phase3 -i phase2_out.csv --limit-groups 5
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parent


def _setup_logging():
    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    logger.add(log_dir / "pipeline.log", level="DEBUG", rotation="10 MB", encoding="utf-8")


def main():
    p = argparse.ArgumentParser(
        description="MOF Literature Mining Pipeline — 3-phase extraction",
    )

    # ── Phase selection ──────────────────────────────────────────────────
    phase = p.add_mutually_exclusive_group(required=True)
    phase.add_argument("--all", action="store_true", help="Run all 3 phases in sequence")
    phase.add_argument("--phase1", action="store_true", help="CSD API -> DOI + unit cell")
    phase.add_argument("--phase2", action="store_true", help="Download papers (main PDF + SI)")
    phase.add_argument("--phase3", action="store_true", help="LLM extraction (BET / synthesis / crystal match)")

    # ── Shared I/O ───────────────────────────────────────────────────────
    p.add_argument("-i", "--input", help="Input CSV/Excel")
    p.add_argument("-o", "--output", help="Output file")
    p.add_argument("--final", default="final_output.xlsx", help="Final output when running --all (default: final_output.xlsx)")

    # ── Phase 2 options ──────────────────────────────────────────────────
    p.add_argument("--limit", type=int, default=0, help="Phase 2: limit unique DOIs to process")
    p.add_argument("--main-only", action="store_true", help="Phase 2: only download main PDFs")
    p.add_argument("--si-only", action="store_true", help="Phase 2: only download SI files")
    p.add_argument("--skip-downloaded", action="store_true", help="Phase 2: skip DOIs with existing paper.pdf")

    # ── Phase 3 options ──────────────────────────────────────────────────
    p.add_argument("--limit-groups", type=int, default=0, help="Phase 3: only process first N PDF groups")
    p.add_argument("--skip-llm-cache", action="store_true")
    p.add_argument("--skip-pdf-cache", action="store_true")
    p.add_argument("--disable-lattice-self-check", action="store_true")
    p.add_argument("--no-checkpoint", action="store_true")

    args = p.parse_args()
    _setup_logging()

    # ── Validate input requirements ──────────────────────────────────────
    if not args.input:
        if not args.all:
            p.error("--input is required when not using --all")
        # --all mode: prompt for input
        p.error("--input is required with --all (CSV with name, predicted_log1p, predicted_mol_kg columns)")

    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        sys.exit(1)

    # ── Phase 1 ──────────────────────────────────────────────────────────
    if args.phase1 or args.all:
        logger.info("=" * 60)
        logger.info("PHASE 1: CSD API -> DOI + unit cell parameters")
        logger.info("=" * 60)

        from phase1_csd import run_phase1

        output_1 = Path(args.output) if args.output else ROOT / "phase1_output.csv"
        if args.all and not args.output:
            output_1 = ROOT / "phase1_output.csv"

        run_phase1(input_path, output_1)
        logger.info(f"Phase 1 complete: {output_1}")

        if args.all:
            args.input = str(output_1)

    # ── Phase 2 ──────────────────────────────────────────────────────────
    if args.phase2 or args.all:
        logger.info("=" * 60)
        logger.info("PHASE 2: DOI -> PDF download (main + SI)")
        logger.info("=" * 60)

        # When running --all, invoke phase2_download module directly
        import csv
        from phase2_download import (
            PAPERS_DIR,
            download_main_pdf,
            update_csv_paths,
            doi_slug,
        )
        from si_download.batch_downloader import download_all_si

        if args.all:
            p2_input = Path(args.input)
        else:
            p2_input = input_path

        # Read CSV
        with open(p2_input, "r", encoding="utf-8") as f:
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

        # Main PDFs
        if not args.si_only:
            logger.info(f"\nPhase 2a: Main PDF download ({len(unique_dois)} DOIs)")
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

        # SI
        if not args.main_only:
            logger.info(f"\nPhase 2b: SI download")
            download_all_si(unique_dois, PAPERS_DIR)

        output_2 = Path(args.output) if args.output else ROOT / "phase2_output.csv"
        if args.all and not args.output:
            output_2 = ROOT / "phase2_output.csv"

        update_csv_paths(p2_input, output_2)
        logger.info(f"Phase 2 complete: {output_2}")

        if args.all:
            args.input = str(output_2)

    # ── Phase 3 ──────────────────────────────────────────────────────────
    if args.phase3 or args.all:
        logger.info("=" * 60)
        logger.info("PHASE 3: LLM extraction (BET / Synthesis / Crystal match)")
        logger.info("=" * 60)

        from phase3_llm import run_extraction

        p3_input = Path(args.input)
        output_3 = Path(args.output) if args.output else Path(args.final)

        run_extraction(
            input_path=p3_input,
            output_path=output_3,
            limit_groups=args.limit_groups,
            skip_llm_cache=args.skip_llm_cache,
            skip_pdf_cache=args.skip_pdf_cache,
            lattice_self_check=not args.disable_lattice_self_check,
            no_checkpoint=args.no_checkpoint,
        )
        logger.info(f"Phase 3 complete: {output_3}")

    logger.info("\nPipeline finished.")


if __name__ == "__main__":
    main()
