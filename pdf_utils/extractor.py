"""PyMuPDF-based text extraction from PDF files."""

from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF
from loguru import logger


def extract_pdf_text(pdf_path: Path) -> str:
    """Extract all text from a PDF. Returns empty string on failure."""
    if not pdf_path.exists():
        logger.warning(f"  PDF not found: {pdf_path}")
        return ""
    try:
        doc = fitz.open(str(pdf_path))
        parts = []
        for page in doc:
            text = page.get_text("text")
            if text:
                parts.append(text)
        doc.close()
        return "\n".join(parts)
    except Exception as e:
        logger.warning(f"  PDF extraction error ({pdf_path}): {e}")
        return ""
