"""Keyword-based paragraph filtering to reduce token consumption.

Keeps only paragraphs matching experimental / synthesis / characterization /
BET / adsorption / crystallographic keywords. If too few paragraphs match,
falls back to keeping the full text.
"""

from __future__ import annotations

import re

# ── Main paper keywords ────────────────────────────────────────────────────
MAIN_KEYWORDS = [
    # Synthesis / experimental
    "synthesis", "synthes", "preparation", "prepared",
    "experimental", "method", "procedure",
    # Characterization / BET
    "bet surface", "brunauer", "surface area",
    "adsorption", "desorption", "isotherm",
    "porosity", "porous", "pore",
    "n2 uptake", "nitrogen isotherm",
    # Crystallography
    "crystal structure", "crystallographic",
    "unit cell", "space group", "cell parameter",
    "single crystal", "single-crystal", "x-ray diffraction",
    # MOF-specific
    "mof", "metal-organic", "metal organic",
    "coordination polymer", "framework",
    "ligand", "sbp", "secondary building",
    # Characterization
    "pxrd", "tga", "ftir", "ir spectrum",
    "thermogravimetric", "elemental analysis",
]

# ── SI keywords (more aggressive filtering) ────────────────────────────────
SI_KEYWORDS = [
    "table s", "figure s", "fig. s",
    "crystallographic", "unit cell", "space group",
    "checkcif", "supporting information",
    "supplementary", "appendix",
    "cell lengths", "crystal data",
]

MIN_MAIN_PARAGRAPHS = 5


def filter_main_text(text: str) -> str:
    """Filter main paper text, keeping relevant paragraphs only."""
    if not text:
        return ""

    paragraphs = _split_paragraphs(text)
    kept = []
    patterns = [re.compile(kw, re.IGNORECASE) for kw in MAIN_KEYWORDS]

    for para in paragraphs:
        if len(para) < 20:
            continue
        for pat in patterns:
            if pat.search(para):
                kept.append(para)
                break

    if len(kept) < MIN_MAIN_PARAGRAPHS:
        return text  # fallback: keep everything

    return "\n\n".join(kept)


def filter_si_text(text: str) -> str:
    """Filter SI text, keeping crystal-structure and table paragraphs."""
    if not text:
        return ""

    paragraphs = _split_paragraphs(text)
    kept = []
    patterns = [re.compile(kw, re.IGNORECASE) for kw in SI_KEYWORDS]

    for para in paragraphs:
        if len(para) < 10:
            continue
        for pat in patterns:
            if pat.search(para):
                kept.append(para)
                break

    return "\n\n".join(kept) if kept else text


def _split_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs by blank lines."""
    blocks = re.split(r"\n\s*\n", text)
    return [b.strip() for b in blocks if b.strip()]
