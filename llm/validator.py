"""Post-hoc validation: BET normalization and lattice evidence checks."""

from __future__ import annotations

import re


def normalize_bet(raw: str | float | int | None) -> float | None:
    """Extract pure numeric BET value from strings like '1532 m2/g'."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    # Remove units, commas, and whitespace
    cleaned = re.sub(r"[,\s]", "", str(raw))
    m = re.search(r"(\d+\.?\d*)", cleaned)
    if m:
        val = float(m.group(1))
        if 10 < val < 20_000:
            return val
    return None


def evidence_supports_lengths(
    evidence_text: str | None,
    a: float | str | None,
    b: float | str | None,
    c: float | str | None,
    rel_tol: float = 0.01,
    abs_tol: float = 0.15,
) -> bool:
    """Check that evidence text contains numbers matching the cell parameters."""
    if not evidence_text or not evidence_text.strip():
        return False

    # Collect non-empty target axes
    targets = []
    for v in (a, b, c):
        try:
            val = float(v)
            if val > 0:
                targets.append(val)
        except (ValueError, TypeError):
            pass

    if not targets:
        return True  # nothing to validate against

    # Extract floating-point numbers from evidence text
    numbers = []
    for m in re.finditer(r"(\d+\.?\d*)", evidence_text):
        try:
            n = float(m.group(1))
            if 1.5 < n < 250.0:
                numbers.append(n)
        except ValueError:
            pass

    if not numbers:
        return False

    # Each target must match at least one extracted number
    matched = 0
    used = set()
    for t in targets:
        for j, n in enumerate(numbers):
            if j in used:
                continue
            rel = abs(t - n) / max(abs(t), abs(n))
            if rel <= rel_tol or abs(t - n) <= abs_tol:
                matched += 1
                used.add(j)
                break

    return matched == len(targets)
