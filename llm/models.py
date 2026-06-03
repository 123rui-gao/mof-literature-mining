"""Pydantic models for LLM extraction output validation."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ExtractedRow(BaseModel):
    """One RefCode's extraction result from LLM."""
    RefCode: str = ""
    Paper_structure_name: str | None = None
    Lattice_match_evidence: str | None = None
    BET: float | int | None = None
    BET_evidence: str | None = None
    Synthesis: str | None = None
    Synthesis_evidence: str | None = None
