"""
Idempotency key derivation for CALL-E call submissions.

The key is derived from (workflow_id, appointment_id, attempt_number)
so that a retry of the same attempt never places a duplicate call.
"""

from __future__ import annotations

import hashlib


def derive_idempotency_key(
    workflow_id: str,
    appointment_id: str,
    attempt_number: int,
) -> str:
    """
    Derive a stable idempotency key for a CALL-E call submission.

    The same inputs always produce the same key, so retrying after a
    network failure cannot submit a duplicate call.
    """
    raw = f"{workflow_id}:{appointment_id}:{attempt_number}"
    return hashlib.sha256(raw.encode()).hexdigest()
