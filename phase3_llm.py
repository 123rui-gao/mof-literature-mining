"""
Phase 3: LLM-based MOF literature extraction (BET, synthesis, crystal structure matching).

Pipeline:
  1. Read input CSV/Excel (RefCode, a, b, c, Main_PDF, SI_Path)
  2. Group by Main_PDF
  3. Extract PDF text via PyMuPDF, filter by keywords
  4. Call DeepSeek LLM to match crystal structures and extract BET/Synthesis
  5. Post-hoc validation (lattice match check, BET normalization)
  6. Write output Excel with 6 extracted columns

Caching:
  - PDF text cache (cache/pdf/<hash>.txt)
  - LLM response cache (cache/llm/<hash>.txt)

Usage:
  python phase3_llm.py -i phase2_output.csv -o final_output.xlsx
  python phase3_llm.py -i phase2_output.csv -o final_output.xlsx --limit-groups 5
  python phase3_llm.py -i phase2_output.csv --from-llm-cache-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import pandas as pd
from loguru import logger

from llm.client import call_deepseek
from llm.models import ExtractedRow
from llm.parser import parse_llm_json
from llm.prompts import SYSTEM_PROMPT, PROMPT_VERSION, build_user_prompt
from llm.validator import normalize_bet, evidence_supports_lengths
from pdf_utils import extract_pdf_text
from pdf_utils.filter import filter_main_text, filter_si_text
from utils.cache import pdf_cache_key, llm_cache_key
from utils.config import Settings, PROJECT_ROOT, PDF_CACHE_DIR, LLM_CACHE_DIR

OUTPUT_COLUMNS = [
    "Paper_structure_name", "Lattice_match_evidence",
    "BET", "BET_evidence", "Synthesis", "Synthesis_evidence",
]


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def load_or_extract_pdf(main_pdf: Path, si_paths: list[Path],
                         skip_pdf_cache: bool = False) -> str:
    """Extract PDF text with caching."""
    if not skip_pdf_cache:
        ck = pdf_cache_key(main_pdf, si_paths, 120_000)
        cache_file = PDF_CACHE_DIR / f"{ck}.txt"
        if cache_file.exists():
            return cache_file.read_text(encoding="utf-8")

    # Extract main PDF
    text = extract_pdf_text(main_pdf)

    # Append SI text
    for si in si_paths:
        si_text = extract_pdf_text(si)
        if si_text:
            text += "\n\n[SUPPORTING INFORMATION]\n" + si_text

    if not skip_pdf_cache and text:
        cache_file = PDF_CACHE_DIR / f"{_hash_text(text)}.txt"
        cache_file.write_text(text, encoding="utf-8")

    return text


def load_or_call_llm(structures: list[dict], literature: str,
                     settings: Settings,
                     skip_llm_cache: bool = False) -> list[dict]:
    """Call LLM with caching. Returns parsed JSON list."""
    payload_json = json.dumps(structures, sort_keys=True, ensure_ascii=False)
    lit_hash = _hash_text(literature)
    ck = llm_cache_key(settings.deepseek_model, PROMPT_VERSION, lit_hash, payload_json)

    if not skip_llm_cache:
        cache_file = LLM_CACHE_DIR / f"{ck}.txt"
        if cache_file.exists():
            raw = cache_file.read_text(encoding="utf-8")
            return parse_llm_json(raw)

    user_prompt = build_user_prompt(structures, literature)
    raw = call_deepseek(SYSTEM_PROMPT, user_prompt, settings)
    result = parse_llm_json(raw)

    if not skip_llm_cache:
        cache_file = LLM_CACHE_DIR / f"{ck}.txt"
        cache_file.write_text(raw, encoding="utf-8")

    return result


def run_extraction(
    input_path: Path,
    output_path: Path,
    limit_groups: int = 0,
    skip_llm_cache: bool = False,
    skip_pdf_cache: bool = False,
    lattice_self_check: bool = True,
    no_checkpoint: bool = False,
) -> dict[str, dict]:
    """Main extraction pipeline. Returns {RefCode: extracted_dict}."""
    settings = Settings()

    # Read input
    if input_path.suffix.lower() == ".csv":
        df = pd.read_csv(input_path)
    else:
        df = pd.read_excel(input_path)

    required = {"RefCode", "Main_PDF"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Input missing required columns: {missing}")

    # Group by Main_PDF
    groups = df.groupby("Main_PDF")
    group_keys = list(groups.groups.keys())
    if limit_groups:
        group_keys = group_keys[:limit_groups]

    logger.info(f"Input: {len(df)} rows, {len(groups)} unique PDFs")
    logger.info(f"Processing: {len(group_keys)} groups")
    if lattice_self_check:
        logger.info("Lattice self-check: ENABLED")
    else:
        logger.info("Lattice self-check: DISABLED")

    all_results: dict[str, dict] = {}
    start_time = time.time()

    for gi, main_pdf in enumerate(group_keys):
        group = groups.get_group(main_pdf)
        refcodes = group["RefCode"].tolist()
        logger.info(f"[{gi + 1}/{len(group_keys)}] {main_pdf} ({len(refcodes)} RefCodes)")

        # Build SI path list
        si_paths = []
        for _, row in group.iterrows():
            si_raw = row.get("SI_Path", "")
            if pd.notna(si_raw) and str(si_raw).strip():
                for p in str(si_raw).split(";"):
                    pp = Path(p.strip())
                    if pp.exists():
                        si_paths.append(pp)

        main_pdf_path = Path(main_pdf)
        if not main_pdf_path.exists():
            logger.warning(f"  Main PDF not found: {main_pdf}")
            continue

        # Extract & filter PDF text
        literature = load_or_extract_pdf(main_pdf_path, si_paths, skip_pdf_cache)
        if not literature:
            logger.warning(f"  No text extracted from {main_pdf}")
            continue

        main_filtered = filter_main_text(literature.split("[SUPPORTING INFORMATION]")[0])
        si_part = ""
        if "[SUPPORTING INFORMATION]" in literature:
            si_part = literature.split("[SUPPORTING INFORMATION]", 1)[1]
        si_filtered = filter_si_text(si_part)
        lit_combined = f"{main_filtered}\n\n[SUPPORTING INFORMATION]\n{si_filtered}"
        logger.info(f"  Text: {len(literature):,} -> {len(lit_combined):,} chars (filtered)")

        # Build structure payload
        structures = []
        for _, row in group.iterrows():
            struct = {"RefCode": row["RefCode"]}
            for axis in ("a", "b", "c"):
                v = row.get(axis)
                if pd.notna(v) and str(v).strip():
                    try:
                        struct[axis] = float(v)
                    except (ValueError, TypeError):
                        pass
            structures.append(struct)

        # Call LLM
        try:
            llm_results = load_or_call_llm(structures, lit_combined, settings, skip_llm_cache)
        except Exception as e:
            logger.error(f"  LLM call failed: {e}")
            continue

        # Map results by RefCode
        by_ref: dict[str, dict] = {}
        for item in llm_results:
            rc = item.get("RefCode", "").strip()
            if rc:
                by_ref[rc] = item

        # Validate and normalize
        for _, row in group.iterrows():
            rc = row["RefCode"]
            extracted = by_ref.get(rc, {})

            # Normalize BET
            if "BET" in extracted and extracted["BET"] is not None:
                extracted["BET"] = normalize_bet(extracted["BET"])

            # Lattice self-check
            if lattice_self_check and extracted.get("Lattice_match_evidence"):
                ok = evidence_supports_lengths(
                    extracted["Lattice_match_evidence"],
                    row.get("a"), row.get("b"), row.get("c"),
                )
                if not ok:
                    logger.warning(f"    {rc}: lattice check FAILED, clearing BET/Synthesis")
                    for field in ("BET", "BET_evidence", "Synthesis", "Synthesis_evidence"):
                        extracted[field] = None

            all_results[rc] = extracted

        # Checkpoint save
        if not no_checkpoint:
            _checkpoint_save(df, all_results, output_path)
            logger.info(f"    Checkpoint: {len(all_results)} RefCodes written")

    # Final save
    _checkpoint_save(df, all_results, output_path)

    elapsed = time.time() - start_time
    logger.info(f"\nDone. {len(all_results)} RefCodes extracted in {elapsed:.0f}s")
    logger.info(f"Output: {output_path}")

    return all_results


def _checkpoint_save(df: pd.DataFrame, results: dict[str, dict], output_path: Path):
    """Merge extraction results into DataFrame and write Excel."""
    df_out = df.copy()
    for col in OUTPUT_COLUMNS:
        df_out[col] = None

    for rc, extracted in results.items():
        mask = df_out["RefCode"] == rc
        if not mask.any():
            continue
        idx = df_out.index[mask][0]
        for col in OUTPUT_COLUMNS:
            val = extracted.get(col)
            if val is not None:
                df_out.at[idx, col] = val

    # Sanitize illegal Excel characters
    for col in OUTPUT_COLUMNS:
        df_out[col] = df_out[col].apply(
            lambda x: str(x).replace("\x00", "").replace("\x08", "")
            if isinstance(x, str) and any(c in str(x) for c in ("\x00", "\x08"))
            else x
        )

    df_out.to_excel(output_path, index=False)


def main():
    p = argparse.ArgumentParser(description="Phase 3: LLM MOF literature extraction")
    p.add_argument("-i", "--input", required=True, help="Input CSV/Excel (Phase 2 output)")
    p.add_argument("-o", "--output", default="phase3_output.xlsx", help="Output Excel")
    p.add_argument("--limit-groups", type=int, default=0, help="Only process first N PDF groups")
    p.add_argument("--skip-llm-cache", action="store_true")
    p.add_argument("--skip-pdf-cache", action="store_true")
    p.add_argument("--disable-lattice-self-check", action="store_true")
    p.add_argument("--no-checkpoint", action="store_true")
    args = p.parse_args()

    # Setup logging
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    logger.add(log_dir / "phase3.log", level="DEBUG", rotation="10 MB", encoding="utf-8")

    run_extraction(
        input_path=Path(args.input),
        output_path=Path(args.output),
        limit_groups=args.limit_groups,
        skip_llm_cache=args.skip_llm_cache,
        skip_pdf_cache=args.skip_pdf_cache,
        lattice_self_check=not args.disable_lattice_self_check,
        no_checkpoint=args.no_checkpoint,
    )


if __name__ == "__main__":
    main()
