"""
ResultValidator — validates a CALL-E CallResult before policy evaluation.

Two validation layers:
  L2 — Pydantic schema validation (enforced by model definitions)
  L3 — Semantic boundary check (rejects forbidden clinical language)
"""

from __future__ import annotations

import re

from medicall.core.models import CallResult


# Patterns that must never appear in result fields.
# Agent deflection phrases ("I'm not in a position to give medical advice",
# "I can't give medical advice") are intentionally safe — only block
# imperative or declarative clinical advice, not the agent's own refusals.
_FORBIDDEN_PATTERNS = [
    re.compile(r"\bdiagnos(is|es|ed|ing)\b", re.IGNORECASE),
    re.compile(r"\bprescri(be|bed|ption|ptions)\b", re.IGNORECASE),
    re.compile(r"\btreatment\s+recommendation\b", re.IGNORECASE),
    re.compile(r"\bclinical\s+conclusion\b", re.IGNORECASE),
    # Match "gave medical advice" / "the medical advice is" but NOT
    # standard agent deflection scripts containing "not" before the phrase.
    re.compile(r"\bgave\s+medical\s+advice\b", re.IGNORECASE),
    re.compile(r"\byou\s+(have|don't\s+have|don't\s+need)\b", re.IGNORECASE),
    re.compile(r"\bsounds?\s+like\s+(it\s+is|it's|just)\b", re.IGNORECASE),
]


class ResultValidator:
    """
    Validates a CallResult against schema rules and semantic boundaries.

    Returns (True, None) on success.
    Returns (False, reason) on failure — caller must route to HUMAN_REVIEW.
    """

    def validate(self, result: CallResult) -> tuple[bool, str | None]:
        """Validate result. Returns (ok, error_message)."""

        # Check for forbidden language in transcript
        if result.transcript:
            for pattern in _FORBIDDEN_PATTERNS:
                if pattern.search(result.transcript):
                    return (
                        False,
                        f"Transcript contains forbidden clinical language "
                        f"matching pattern: {pattern.pattern}",
                    )

        # Check patient report fields
        if result.intake:
            for report in result.intake.patient_reports:
                for pattern in _FORBIDDEN_PATTERNS:
                    if pattern.search(report.patient_statement):
                        return (
                            False,
                            f"Patient report contains forbidden clinical language "
                            f"matching pattern: {pattern.pattern}",
                        )

        return True, None
