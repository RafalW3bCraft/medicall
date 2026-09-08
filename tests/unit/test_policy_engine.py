"""Tests for the PolicyEngine — all 8 rules."""
from __future__ import annotations

import pytest

from medicall.core.models import AppointmentSlot, CallResult, IntakeResult, PatientReport
from medicall.engine.policy import PolicyEngine


def _make_result(
    calle_status: str = "COMPLETED",
    confirmed: bool = True,
    reschedule: bool = False,
    rescheduled_to=None,
    reports: list | None = None,
    consent: bool = True,
    call_completed: bool = True,
) -> CallResult:
    intake = IntakeResult(
        appointment_confirmed=confirmed,
        reschedule_requested=reschedule,
        rescheduled_to=rescheduled_to,
        patient_reports=reports or [],
        consent_given=consent,
        call_completed=call_completed,
    )
    return CallResult(run_id="test-run", calle_status=calle_status, intake=intake)


@pytest.fixture
def engine():
    return PolicyEngine()


def test_r01_confirmed_no_reports(engine):
    result = _make_result(confirmed=True, reports=[])
    decision = engine.evaluate(result)
    assert decision.disposition == "ROUTINE"
    assert "R01_confirmed_no_reports" in decision.triggered_rules


def test_r02_reschedule_with_slot(engine):
    slot = AppointmentSlot(date="2026-09-01", time="14:30", label="Tuesday 1 Sep at 2:30 PM")
    result = _make_result(confirmed=False, reschedule=True, rescheduled_to=slot, reports=[])
    decision = engine.evaluate(result)
    assert decision.disposition == "ROUTINE"
    assert "R02_reschedule_confirmed" in decision.triggered_rules
    assert decision.workflow_action == "update_appointment_slot"


def test_r02_reschedule_without_slot(engine):
    result = _make_result(confirmed=False, reschedule=True, rescheduled_to=None, reports=[])
    decision = engine.evaluate(result)
    assert decision.disposition == "HUMAN_REVIEW"
    assert "R02_reschedule_no_slot" in decision.triggered_rules


def test_r03_new_symptom_triggers_human_review(engine):
    report = PatientReport(
        patient_statement="I've had chest pain since yesterday.",
        normalized_description="chest pain, onset yesterday",
    )
    result = _make_result(confirmed=True, reports=[report])
    decision = engine.evaluate(result)
    assert decision.disposition == "HUMAN_REVIEW"
    assert "R03_new_symptom_reported" in decision.triggered_rules
    assert len(decision.evidence) == 1
    assert decision.workflow_action == "route_to_nurse_queue"


def test_r04_consent_declined(engine):
    result = _make_result(consent=False, reports=[])
    decision = engine.evaluate(result)
    assert decision.disposition == "ROUTINE"
    assert "R04_consent_declined" in decision.triggered_rules


def test_r06_no_answer(engine):
    result = CallResult(run_id="test-run", calle_status="NO_ANSWER", intake=None)
    decision = engine.evaluate(result)
    assert decision.disposition == "ROUTINE"
    assert "R06_no_answer_max_attempts" in decision.triggered_rules
    assert decision.workflow_action == "flag_for_manual_followup"


def test_r07_call_failed(engine):
    result = CallResult(run_id="test-run", calle_status="FAILED", intake=None)
    decision = engine.evaluate(result)
    assert decision.disposition == "HUMAN_REVIEW"
    assert "R07_call_failed" in decision.triggered_rules


def test_evidence_includes_patient_statement(engine):
    report = PatientReport(
        patient_statement="Severe headache for three days.",
        normalized_description="severe headache, duration three days",
        call_offset_seconds=55,
    )
    result = _make_result(confirmed=True, reports=[report])
    decision = engine.evaluate(result)
    assert decision.evidence[0].patient_statement == "Severe headache for three days."
    assert decision.evidence[0].call_offset_seconds == 55
