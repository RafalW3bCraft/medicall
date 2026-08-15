"""
Acceptance test for RealCallEAdapter.

This test places a REAL outbound CALL-E phone call via the `calle` CLI.
It is SKIPPED by default and ONLY runs when both env vars are set:

    CALLE_ACCEPTANCE=1
    ACCEPTANCE_PHONE=+<your E.164 number>

Run with:
    CALLE_ACCEPTANCE=1 ACCEPTANCE_PHONE=+918160094043 \\
        pytest tests/acceptance/test_real_adapter.py -v -s

Requirements:
    - `calle` CLI installed (npm install -g @call-e/cli)
    - `calle auth status` must report usable=true
    - You must have available CALL-E call credits
    - The phone number must be your own — this places a real outbound call

DO NOT run this in CI or automated pipelines.
"""

from __future__ import annotations

import os

import pytest

from medicall.calle.real_adapter import RealCallEAdapter, _find_calle_binary
from medicall.core.idempotency import derive_idempotency_key
from medicall.core.models import CallTask
from medicall.core.state_machine import CALLE_TERMINAL_STATUSES

# ── Guard: skip unless explicitly opted in ────────────────────────────────────

ACCEPTANCE_ENABLED = os.getenv("CALLE_ACCEPTANCE", "").strip() == "1"
ACCEPTANCE_PHONE = os.getenv("ACCEPTANCE_PHONE", "").strip()

pytestmark = pytest.mark.skipif(
    not ACCEPTANCE_ENABLED or not ACCEPTANCE_PHONE,
    reason=(
        "Acceptance test skipped. "
        "Set CALLE_ACCEPTANCE=1 and ACCEPTANCE_PHONE=+<your number> to run."
    ),
)

# ── Test ──────────────────────────────────────────────────────────────────────

def test_calle_binary_found() -> None:
    """Verify the calle CLI is locatable before attempting a real call."""
    cmd = _find_calle_binary()
    assert cmd, "calle binary not found"
    print(f"\n   calle binary: {' '.join(cmd)}")


@pytest.mark.asyncio
async def test_real_adapter_single_call() -> None:
    """
    Places a single real CALL-E call to ACCEPTANCE_PHONE via calle CLI.

    Verifies:
    1. calle call start → calle call status poll loop completes
    2. The returned CallResult has a run_id and a terminal calle_status
    3. No forbidden clinical fields appear in any result field
    """
    adapter = RealCallEAdapter()

    task = CallTask(
        appointment_id="acceptance-test-appt-001",
        workflow_id="acceptance-test-wf-001",
        attempt_number=1,
        phone=ACCEPTANCE_PHONE,
        goal=(
            "This is a test call from MediCall, a CALL-E hackathon project. "
            "Please say 'test confirmed' and end the call. "
            "This is only a development verification call."
        ),
        language="English",
        region=None,
        idempotency_key=derive_idempotency_key(
            "acceptance-test-wf-001",
            "acceptance-test-appt-001",
            1,
        ),
    )

    print(f"\n▶  Placing real CALL-E call to {ACCEPTANCE_PHONE} ...")
    result = await adapter.execute(task)

    # 1. run_id must be a non-empty string
    assert result.run_id, "run_id must be non-empty"
    print(f"   run_id: {result.run_id}")

    # 2. calle_status must be a known terminal status
    assert result.calle_status in CALLE_TERMINAL_STATUSES, (
        f"Expected terminal status, got: {result.calle_status}"
    )
    print(f"   calle_status: {result.calle_status}")

    # 3. No forbidden clinical fields in intake
    if result.intake:
        assert not hasattr(result.intake, "diagnosis"), (
            "intake must not contain 'diagnosis' field"
        )
        assert not hasattr(result.intake, "clinical_recommendation"), (
            "intake must not contain 'clinical_recommendation' field"
        )
        print(f"   appointment_confirmed: {result.intake.appointment_confirmed}")
        print(f"   patient_reports: {len(result.intake.patient_reports)}")

    # 4. Transcript present if call was answered
    if result.calle_status == "COMPLETED" and result.transcript:
        print(f"   transcript preview: {result.transcript[:120]}...")

    print(f"   duration_seconds: {result.duration_seconds}")
    print(f"   call_id: {result.call_id}")
    print("   ✓ RealCallEAdapter acceptance test passed")
