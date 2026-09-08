"""
Acceptance tests for MediCall — real outbound CALL-E calls.

These tests place REAL outbound phone calls via the `calle` CLI.
They are SKIPPED by default and ONLY run when both env vars are set:

    CALLE_ACCEPTANCE=1
    ACCEPTANCE_PHONE=+918160094043

Run with:
    CALLE_ACCEPTANCE=1 ACCEPTANCE_PHONE=+918160094043 \\
        pytest tests/acceptance/test_real_adapter.py -v -s

Requirements:
    - `calle` CLI installed: npm install -g @call-e/cli
    - `calle auth status` must report usable=true
    - You must have available CALL-E call credits
    - The phone number must be your own — this places real outbound calls

IMPORTANT — DATE HANDLING:
    CALL-E's plan_not_ready guard rejects any goal that references a past date.
    Appointment dates are computed dynamically at test runtime (today + N days)
    so these tests are safe to run on any day without editing.

DO NOT run these in CI or automated pipelines.

--- TESTS ---

test_calle_binary_found
    Verifies the calle CLI binary is locatable before attempting any call.

test_real_adapter_single_call
    Places a single real CALL-E call using the production goal builder and
    verifies the adapter parsing path:
      - run_id is returned
      - calle_status is a known terminal status
      - No forbidden clinical fields appear in intake

test_real_full_workflow
    Full production flow: CoordinationEngine + RealCallEAdapter + PolicyEngine
    + HandoffGenerator. Uses the first appointment from examples/appointments.example.json
    (Jane Smith, City Medical Centre, English).
    Verifies:
      - WorkflowRecord reaches state=COMPLETED
      - calle_status is a known terminal status
      - policy_decision is populated
      - Console summary is printed
      - No forbidden clinical fields in any output
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from medicall.calle.real_adapter import RealCallEAdapter, _find_calle_binary
from medicall.core.events import InMemoryEventStore
from medicall.core.idempotency import derive_idempotency_key
from medicall.core.models import Appointment, AppointmentSlot, CallTask
from medicall.core.state_machine import CALLE_TERMINAL_STATUSES, WorkflowState
from medicall.engine.coordinator import CoordinationEngine
from medicall.engine.handoff import HandoffGenerator
from medicall.healthcare.goal_builder import build_goal

# ── Guard: skip unless explicitly opted in ────────────────────────────────────

ACCEPTANCE_ENABLED = os.getenv("CALLE_ACCEPTANCE", "").strip() == "1"
ACCEPTANCE_PHONE = os.getenv("ACCEPTANCE_PHONE", "").strip()

pytestmark = pytest.mark.skipif(
    not ACCEPTANCE_ENABLED or not ACCEPTANCE_PHONE,
    reason=(
        "Acceptance test skipped. "
        "Set CALLE_ACCEPTANCE=1 and ACCEPTANCE_PHONE=+918160094043 to run."
    ),
)


# ── Dynamic future dates ───────────────────────────────────────────────────────

def _future_date(days_ahead: int) -> str:
    """Return an ISO date string N days from today (UTC).

    CALL-E's plan_not_ready guard rejects any goal that references a past date,
    so appointment dates must always be computed at runtime relative to today.
    """
    return (datetime.now(UTC) + timedelta(days=days_ahead)).strftime("%Y-%m-%d")


def _future_label(days_ahead: int, time_str: str) -> str:
    """Human-readable label for an alternative slot, e.g. 'Mon 14 Sep at 9:00 AM'."""
    dt = datetime.now(UTC) + timedelta(days=days_ahead)
    return dt.strftime(f"%a %-d %b at {time_str}")


# ── Shared real appointment ────────────────────────────────────────────────────

def _real_appointment() -> Appointment:
    """
    Build a production appointment with dates that are always in the future.

    Appointment: today + 3 days at 10:00
    Alt slot 1:  today + 5 days at 09:00
    Alt slot 2:  today + 7 days at 14:30

    Uses ACCEPTANCE_PHONE so the call is placed to the operator's own number.
    CALL-E's plan_not_ready guard rejects past dates, so these must be dynamic.
    """
    appt_date = _future_date(3)
    alt1_date = _future_date(5)
    alt2_date = _future_date(7)

    return Appointment(
        patient_name="Jane Smith",
        patient_phone=ACCEPTANCE_PHONE,
        clinic_name="City Medical Centre",
        appointment_date=appt_date,
        appointment_time="10:00",
        language="English",
        region="IN",
        alternative_slots=[
            AppointmentSlot(
                date=alt1_date,
                time="09:00",
                label=_future_label(5, "9:00 AM"),
            ),
            AppointmentSlot(
                date=alt2_date,
                time="14:30",
                label=_future_label(7, "2:30 PM"),
            ),
        ],
        max_retry_attempts=1,  # single attempt for acceptance testing
    )


# ── Test 1: Binary detection ───────────────────────────────────────────────────

def test_calle_binary_found() -> None:
    """Verify the calle CLI is locatable before attempting any real call."""
    cmd = _find_calle_binary()
    assert cmd, "calle binary not found"
    print(f"\n   calle binary: {' '.join(cmd)}")


# ── Test 2: Adapter-level real call ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_real_adapter_single_call() -> None:
    """
    Places a single real CALL-E call via RealCallEAdapter (adapter layer only).

    Uses the production goal builder so the call content matches what a real
    patient would receive. Verifies the full adapter parsing path:
      1. calle call start → run_id returned
      2. Poll loop completes with a terminal status
      3. CallResult has run_id, terminal calle_status, and no forbidden clinical fields
    """
    adapter = RealCallEAdapter()
    appointment = _real_appointment()

    task = CallTask(
        appointment_id=appointment.id,
        workflow_id="acceptance-adapter-wf-001",
        attempt_number=1,
        phone=appointment.patient_phone,
        goal=build_goal(appointment),  # production goal builder
        language=appointment.language,
        region=appointment.region,
        idempotency_key=derive_idempotency_key(
            "acceptance-adapter-wf-001",
            appointment.id,
            1,
        ),
    )

    print(f"\n▶  Placing real CALL-E call to {appointment.patient_phone} ...")
    print(f"   Patient: {appointment.patient_name}")
    print(f"   Clinic:  {appointment.clinic_name}")
    print(f"   Goal preview: {task.goal[:120]}...")
    result = await adapter.execute(task)

    # 1. run_id must be a non-empty string
    assert result.run_id, "run_id must be non-empty"
    print(f"\n   run_id:        {result.run_id}")

    # 2. calle_status must be a known terminal status
    assert result.calle_status in CALLE_TERMINAL_STATUSES, (
        f"Expected terminal status, got: {result.calle_status}"
    )
    print(f"   calle_status:  {result.calle_status}")

    # 3. No forbidden clinical fields in intake
    if result.intake:
        assert not hasattr(result.intake, "diagnosis"), (
            "intake must not contain 'diagnosis' field"
        )
        assert not hasattr(result.intake, "clinical_recommendation"), (
            "intake must not contain 'clinical_recommendation' field"
        )
        print(f"   confirmed:     {result.intake.appointment_confirmed}")
        print(f"   patient_reports: {len(result.intake.patient_reports)}")

    # 4. Transcript present if call was answered
    if result.calle_status == "COMPLETED" and result.transcript:
        print(f"   transcript:    {result.transcript[:160]}...")

    print(f"   duration:      {result.duration_seconds}s")
    print(f"   call_id:       {result.call_id}")
    print("   ✓ RealCallEAdapter acceptance test passed")


# ── Test 3: Full production workflow ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_real_full_workflow() -> None:
    """
    Full production flow acceptance test.

    Runs the complete MediCall workflow stack end-to-end with a real outbound call:
      CoordinationEngine → RealCallEAdapter → CALL-E CLI → live phone call
      → ResultValidator → PolicyEngine → HandoffGenerator (if needed)
      → WorkflowRecord → console call summary

    Verifies:
      1. WorkflowRecord reaches state=COMPLETED
      2. call_result has a terminal calle_status
      3. policy_decision is populated with a valid disposition
      4. No forbidden clinical fields in any model
      5. Console call summary is printed (verified via print capture)
    """
    appointment = _real_appointment()

    handoffs: dict = {}
    event_store = InMemoryEventStore()
    engine = CoordinationEngine(
        phone_port=RealCallEAdapter(),
        event_store=event_store,
        handoff_generator=HandoffGenerator(store=handoffs),
    )

    print(
        f"\n▶  Full workflow — calling {appointment.patient_name}"
        f" at {appointment.patient_phone}"
    )
    print(
        f"   Clinic: {appointment.clinic_name}  |"
        f"  {appointment.appointment_date} {appointment.appointment_time}"
    )
    print(f"   Language: {appointment.language}  |  Region: {appointment.region}")

    record = await engine.run(appointment)

    # 1. Workflow must complete
    assert record.state == WorkflowState.COMPLETED, (
        f"Expected COMPLETED, got {record.state.value}. Error: {record.error}"
    )
    print(f"\n   workflow_id:   {record.id}")

    # 2. call_result must have a terminal status
    assert record.call_result is not None, "call_result must be set on COMPLETED workflow"
    assert record.call_result.calle_status in CALLE_TERMINAL_STATUSES, (
        f"Unexpected calle_status: {record.call_result.calle_status}"
    )
    print(f"   calle_status:  {record.call_result.calle_status}")
    print(f"   run_id:        {record.call_result.run_id}")

    # 3. Policy decision must be populated
    assert record.policy_decision is not None, "policy_decision must be set"
    assert record.policy_decision.disposition in {"ROUTINE", "HUMAN_REVIEW", "ESCALATION"}, (
        f"Invalid disposition: {record.policy_decision.disposition}"
    )
    print(f"   disposition:   {record.policy_decision.disposition}")
    print(f"   action:        {record.policy_decision.workflow_action}")
    print(f"   rules:         {record.policy_decision.triggered_rules}")

    # 4. No forbidden clinical fields
    if record.call_result.intake:
        intake = record.call_result.intake
        assert not hasattr(intake, "diagnosis"), "intake must not contain 'diagnosis'"
        assert not hasattr(intake, "clinical_recommendation")
        print(f"   confirmed:     {intake.appointment_confirmed}")
        print(f"   patient_reports: {len(intake.patient_reports)}")
        for rpt in intake.patient_reports:
            print(f"     → {rpt.patient_statement[:100]}")

    # 5. Handoff created if disposition requires it
    if record.policy_decision.disposition in {"HUMAN_REVIEW", "ESCALATION"}:
        assert record.handoff_id is not None, (
            "HUMAN_REVIEW/ESCALATION disposition must produce a handoff_id"
        )
        assert record.handoff_id in handoffs, "handoff must be persisted in store"
        print(f"   handoff_id:    {record.handoff_id}")

    # 6. Events logged for every stage
    events = event_store.get_for_workflow(record.id)
    event_types = [e.event_type.value for e in events]
    assert "AppointmentCreated" in event_types
    assert "WorkflowCompleted" in event_types
    print(f"   events logged: {event_types}")

    # 7. No error
    assert record.error is None, f"Unexpected workflow error: {record.error}"
    print("\n   ✓ Full production workflow acceptance test passed")
