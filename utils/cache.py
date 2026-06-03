"""Deterministic cache key generation (SHA-256)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def pdf_cache_key(
    main_pdf: Path,
    si_paths: list[Path],
    max_chars: int,
) -> str:
    """Cache key for extracted PDF text, based on file paths, sizes, and mtimes."""
    parts: list[str] = []
    for p in [main_pdf] + si_paths:
        if p and p.exists():
            st = p.stat()
            parts.append(f"{p.resolve()}:{st.st_size}:{int(st.st_mtime)}")
    parts.append(str(max_chars))
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()


def llm_cache_key(
    model: str,
    prompt_version: str,
    literature_hash: str,
    mof_payload_json: str,
) -> str:
    """Cache key for LLM responses."""
    raw = f"{model}|{prompt_version}|{literature_hash}|{mof_payload_json}"
    return hashlib.sha256(raw.encode()).hexdigest()
