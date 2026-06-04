"""
Phase 1: Fetch DOIs and unit cell parameters from CSD Python API.

Strategies (tried in order):
  1. 6-letter CSD refcode (e.g., AVEQID)
  2. 6-letter refcode + digits (e.g., FIRNAX01)
  3. Refcode with _ASR_pacman suffix
  4. SI filename -> construct article DOI -> search CSD by DOI
     (e.g., c5sc03494a2_2_ASR_pacman -> 10.1039/C5SC03494A)

Usage:
    python phase1_csd.py -i input.csv -o output.csv

Requires: CCDC CSD Python API (ccdc package) installed in the environment.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path

# ── ACS journal SI filename prefixes ──────────────────────────────────────
ACS_PREFIXES = {
    "ja": "jacs", "cm": "cm", "nl": "nl", "am": "am",
    "cg": "cg", "ol": "ol", "ic": "ic",
}

# ── RSC journal abbreviations ─────────────────────────────────────────────
RSC_JOURNALS = {
    "sc": "Chem. Sci.", "dt": "Dalton Trans.", "nj": "New J. Chem.",
    "ce": "CrystEngComm", "ta": "J. Mater. Chem. A", "tb": "J. Mater. Chem. B",
    "tc": "J. Mater. Chem. C", "gc": "Green Chem.", "qi": "Mater. Chem. Front.",
    "ra": "RSC Adv.", "fo": "Mater. Horiz.", "cc": "Chem. Commun.",
    "cy": "Chem. Commun.", "an": "Analyst", "ay": "Analyst",
    "nr": "Nanoscale", "na": "Nanoscale", "cp": "Phys. Chem. Chem. Phys.",
    "py": "Polym. Chem.", "me": "Med. Chem. Commun.", "mt": "Metallomics",
    "lc": "Lab Chip", "fd": "Faraday Discuss.", "rx": "React. Chem. Eng.",
    "sm": "Sustainable Energy Fuels",
}


def extract_refcode_candidates(name: str) -> list[str]:
    """Extract potential CSD refcode identifiers from the name field."""
    candidates = []
    base = name.replace("_ASR_pacman", "")

    if re.match(r"^[A-Z]{6}$", base):
        candidates.append(base)
    elif re.match(r"^[A-Z]{6}\d{2}$", base):
        candidates.append(base[:6])
        candidates.append(base)
    elif m := re.match(r"^([A-Z]{6})_", base):
        candidates.append(m.group(1))

    return candidates


def strip_si_suffix(article_id: str) -> str:
    """Strip trailing 'si' from ACS article IDs (SI marker, not part of code)."""
    if article_id.endswith("si") and len(article_id) > 4:
        return article_id[:-2]
    return article_id


def construct_article_doi_from_si(name: str) -> str | None:
    """Try to construct article DOI from a journal SI filename pattern."""
    base = name.replace("_ASR_pacman", "")

    # ACS: {prefix}{article}_si_{num}
    si_match = re.match(r"^([a-z]{2}\d+\w+?)_si_\d+", base)
    if si_match:
        article_id = strip_si_suffix(si_match.group(1))
        if article_id[:2] in ACS_PREFIXES:
            return f"10.1021/{article_id}"

    # ACS: date-based pattern {prefix}{article}{YYYYMMDD}_{num}
    date_match = re.match(r"^([a-z]{2}\d+[a-z]+?)(\d{8})_(\d+)", base)
    if date_match:
        article_id = strip_si_suffix(date_match.group(1))
        if article_id[:2] in ACS_PREFIXES:
            return f"10.1021/{article_id}"

    # RSC: {c|d}{year}{jj}{5digits}{check_letter}{struct_num?}
    rsc_match = re.match(r"^([cd]\d[a-z]{2}\d{5}[a-z])\d?", base)
    if rsc_match:
        return f"10.1039/{rsc_match.group(1).upper()}"

    return None


def get_doi_from_entry(entry: object) -> str | None:
    """Extract publication DOI from a CSD entry."""
    try:
        doi = entry.publication.doi
        if doi:
            return doi.strip()
    except Exception:
        pass
    return None


def get_cell_params_from_entry(entry: object) -> dict[str, str]:
    """Extract unit cell parameters (a,b,c,alpha,beta,gamma) from a CSD entry."""
    result = {"a": "", "b": "", "c": "", "alpha": "", "beta": "", "gamma": ""}
    try:
        cell = entry.crystal
        if cell:
            lengths = cell.cell_lengths
            angles = cell.cell_angles
            if lengths:
                result["a"] = f"{lengths[0]:.4f}"
                result["b"] = f"{lengths[1]:.4f}"
                result["c"] = f"{lengths[2]:.4f}"
            if angles:
                result["alpha"] = f"{angles[0]:.4f}"
                result["beta"] = f"{angles[1]:.4f}"
                result["gamma"] = f"{angles[2]:.4f}"
    except Exception:
        pass
    return result


def lookup_by_refcode(refcode: str, csd_reader: object) -> object | None:
    """Fetch a CSD entry by refcode."""
    try:
        return csd_reader.entry(refcode)
    except Exception:
        return None


def lookup_by_doi(doi: str, csd_reader: object) -> list:
    """Search CSD for entries matching a publication DOI."""
    entries = []
    # Method 1: TextNumericSearch
    try:
        from ccdc.search import TextNumericSearch
        searcher = TextNumericSearch()
        searcher.add_doi(doi)
        for hit in searcher.search():
            entries.append(hit.entry)
        if entries:
            return entries
    except Exception:
        pass
    # Method 2: IdentifierSearch
    try:
        from ccdc.search import Search
        results = Search.search(identifier=doi, database="CSD")
        for r in results:
            entries.append(r.entry)
        if entries:
            return entries
    except Exception:
        pass
    # Method 3: direct identifier lookup
    try:
        entry = csd_reader.entry(doi)
        if entry:
            entries.append(entry)
    except Exception:
        pass
    return entries


def run_phase1(input_csv: Path, output_csv: Path) -> Path:
    """
    Run Phase 1: CSD API -> DOI + unit cell.

    Input CSV must have these columns: name, predicted_log1p, predicted_mol_kg
    Output CSV will add: RefCode, doi, a, b, c, alpha, beta, gamma, status
    """
    from ccdc import io

    rows = []
    with open(input_csv, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)

    print(f"Input: {len(rows)} entries from {input_csv}")

    csd_reader = io.EntryReader("CSD")
    results = []
    found = 0

    for i, row in enumerate(rows):
        name = row["name"].strip()
        doi = None
        matched_id = None
        method = None
        cell = {"a": "", "b": "", "c": "", "alpha": "", "beta": "", "gamma": ""}

        # Strategy A: refcode lookup
        for candidate in extract_refcode_candidates(name):
            entry = lookup_by_refcode(candidate, csd_reader)
            if entry:
                doi = get_doi_from_entry(entry)
                if doi:
                    matched_id = candidate
                    method = "refcode"
                    cell = get_cell_params_from_entry(entry)
                    break

        # Strategy B: SI filename -> article DOI -> CSD lookup
        if not doi:
            article_doi = construct_article_doi_from_si(name)
            if article_doi:
                csd_entries = lookup_by_doi(article_doi, csd_reader)
                if csd_entries:
                    doi = get_doi_from_entry(csd_entries[0])
                    if doi:
                        matched_id = csd_entries[0].identifier
                        method = "si_doi_csd"
                        cell = get_cell_params_from_entry(csd_entries[0])
                if not doi:
                    doi = article_doi
                    matched_id = article_doi
                    method = "si_doi_constructed"

        if doi:
            found += 1
            status = method or "found"
        else:
            status = "not_found"

        results.append({
            "name": name,
            "predicted_log1p": row.get("predicted_log1p", ""),
            "predicted_mol_kg": row.get("predicted_mol_kg", ""),
            "RefCode": matched_id or "",
            "doi": doi or "",
            "a": cell["a"], "b": cell["b"], "c": cell["c"],
            "alpha": cell["alpha"], "beta": cell["beta"], "gamma": cell["gamma"],
            "status": status,
        })

        if (i + 1) % 50 == 0 or i == len(rows) - 1:
            print(f"  [{i + 1}/{len(rows)}] found: {found}, not_found: {i + 1 - found}")

    fieldnames = [
        "name", "predicted_log1p", "predicted_mol_kg",
        "RefCode", "doi",
        "a", "b", "c", "alpha", "beta", "gamma", "status",
    ]
    with open(output_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    method_counts = Counter(r["status"] for r in results)
    print(f"\nDone. {found}/{len(rows)} found ({found / len(rows) * 100:.1f}%)")
    for m, c in sorted(method_counts.items()):
        print(f"  {m}: {c}")
    print(f"Output: {output_csv}")
    return output_csv


def main():
    p = argparse.ArgumentParser(description="Phase 1: CSD API -> DOI + unit cell parameters")
    p.add_argument("-i", "--input", required=True, help="Input CSV (name, predicted_log1p, predicted_mol_kg)")
    p.add_argument("-o", "--output", default="phase1_output.csv", help="Output CSV")
    args = p.parse_args()
    run_phase1(Path(args.input), Path(args.output))


if __name__ == "__main__":
    main()
