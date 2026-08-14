"""
Integration tests for CoordinationEngine using MockCallEAdapter.

All 10 acceptance scenarios from the Phase 0 spec are exercised here.
No real CALL-E calls are made.
"""
from __future__ import annotations
import pytest
from medicall.calle.mock_adapter import MockCallEAdapter
from medicall.core.events import InMemoryEventStore
from medicall.core.models import Appointment, AppointmentSlot
from medicall.core.state_machine import WorkflowState
from medicall.engine.coordinator import CoordinationEngine


def _make_appointment(**kwargs) -> Appointment:
    defaults = dict(
        patient_name="Test Patient",
        patient_phone="+15550000001",
        clinic_name="Test Clinic",
        appointment_date="2026-08-17",
        appointment_time="10:00",
        language="English",
        alternative_slots=[
            AppointmentSlot(date="2026-08-20", time="14:30", label="Thu 20 Aug at 2:30 PM")
        ],
        max_retry_attempts=3,
    )
    defaults.update(kwargs)
    return Appointment(**defaults)


def _engine(scenario: str) -> tuple[CoordinationEngine, InMemoryEventStore]:
    store = InMemoryEventStore()
    engine = CoordinationEngine(
        phone_port=MockCallEAdapter(scenario=scenario),
        event_store=store,
    )
    return engine, store


# ── Scenario 001: Appointment confirmed, no reports → ROUTINE ────────────────

@pytest.mark.asyncio
async def test_scenario_001_confirm():
    engine, store = _engine("scenario_001_confirm")
    record = await engine.run(_make_appointment())
    assert record.state == WorkflowState.COMPLETED
    assert record.policy_decision.disposition == "ROUTINE"
    assert record.error is None


# ── Scenario 002: Reschedule requested, slot confirmed → ROUTINE ─────────────

@pytest.mark.asyncio
async def test_scenario_002_reschedule():
    engine, store = _engine("scenario_002_reschedule")
    record = await engine.run(_make_appointment())
    assert record.state == WorkflowState.COMPLETED
    assert record.policy_decision.disposition == "ROUTINE"
    assert record.policy_decision.workflow_action == "update_appointment_slot"


# ── Scenario 003: No answer → RETRY_PENDING then COMPLETED ───────────────────

@pytest.mark.asyncio
async def test_scenario_003_no_answer():
    engine, store = _engine("scenario_003_no_answer")
    # max_retry_attempts=1 so it terminates after one attempt
    record = await engine.run(_make_appointment(max_retry_attempts=1))
    assert record.state == WorkflowState.COMPLETED
    assert record.policy_decision.workflow_action == "flag_for_manual_followup"


# ── Scenario 004: Consent declined → ROUTINE, no intake data ─────────────────

@pytest.mark.asyncio
async def test_scenario_004_consent_declined():
    engine, store = _engine("scenario_004_consent_declined")
    record = await engine.run(_make_appointment())
    assert record.state == WorkflowState.COMPLETED
    assert record.policy_decision.disposition == "ROUTINE"
    # No patient reports because consent was declined
    assert record.call_result.intake.patient_reports == []


# ── Scenario 005: New symptom → HUMAN_REVIEW, evidence populated ─────────────

@pytest.mark.asyncio
async def test_scenario_005_new_symptom():
    engine, store = _engine("scenario_005_new_symptom")
    record = await engine.run(_make_appointment())
    assert record.state == WorkflowState.COMPLETED
    assert record.policy_decision.disposition == "HUMAN_REVIEW"
    assert len(record.policy_decision.evidence) > 0
    assert record.handoff_id is not None


# ── Scenario 006: Ambiguous response → HUMAN_REVIEW ─────────────────────────

@pytest.mark.asyncio
async def test_scenario_006_ambiguous():
    engine, store = _engine("scenario_006_ambiguous")
    record = await engine.run(_make_appointment())
    assert record.state == WorkflowState.COMPLETED
    # Ambiguous report still triggers R03 (any patient report → HUMAN_REVIEW)
    assert record.policy_decision.disposition == "HUMAN_REVIEW"


# ── Scenario 007: Medical advice boundary ────────────────────────────────────

@pytest.mark.asyncio
async def test_scenario_007_medical_advice_boundary():
    engine, store = _engine("scenario_007_medical_advice_boundary")
    record = await engine.run(_make_appointment())
    assert record.state == WorkflowState.COMPLETED
    # Patient report is recorded but no diagnosis field exists
    intake = record.call_result.intake
    assert intake is not None
    assert not hasattr(intake, "diagnosis")
    assert len(intake.patient_reports) > 0


# ── Scenario 008: Escalation path → HUMAN_REVIEW + handoff ───────────────────

@pytest.mark.asyncio
async def test_scenario_008_escalation():
    engine, store = _engine("scenario_008_escalation")
    record = await engine.run(_make_appointment())
    assert record.state == WorkflowState.COMPLETED
    assert record.policy_decision.disposition == "HUMAN_REVIEW"
    assert record.handoff_id is not None


# ── Scenario 009: Idempotency — same appointment submitted twice ──────────────

@pytest.mark.asyncio
async def test_scenario_009_idempotency():
    """
    The same appointment can be run through the engine multiple times,
    but each run should have a distinct workflow_id and attempt_number,
    producing a distinct idempotency_key. The mock adapter tracks call_count.
    """
    mock = MockCallEAdapter(scenario="scenario_001_confirm")
    store = InMemoryEventStore()
    engine = CoordinationEngine(phone_port=mock, event_store=store)

    appt = _make_appointment()
    record1 = await engine.run(appt)

    # Idempotency key is derived from workflow_id + appointment_id + attempt.
    # A second engine.run creates a NEW workflow_id, so it's a new workflow —
    # not a duplicate. The underlying CALL-E call uses unique idempotency keys.
    record2 = await engine.run(appt)

    assert record1.id != record2.id
    assert mock.call_count == 2  # Two distinct calls, two distinct keys


# ── Scenario 010: Max retries → COMPLETED with flag ──────────────────────────

@pytest.mark.asyncio
async def test_scenario_010_max_retries():
    mock = MockCallEAdapter(scenario="scenario_003_no_answer")
    store = InMemoryEventStore()
    engine = CoordinationEngine(phone_port=mock, event_store=store)

    record = await engine.run(_make_appointment(max_retry_attempts=3))
    assert record.state == WorkflowState.COMPLETED
    # Should have retried up to max_retry_attempts times
    assert mock.call_count == 3
