"""Tests for the ResultValidator — schema and semantic boundary checks."""
from __future__ import annotations
import pytest
from medicall.core.models import CallResult, IntakeResult, PatientReport
from medicall.engine.validator import ResultValidator


@pytest.fixture
def validator():
    return ResultValidator()


def _result_with_transcript(transcript: str) -> CallResult:
    return CallResult(run_id="test", calle_status="COMPLETED", transcript=transcript)


def test_clean_transcript_passes(validator):
    result = _result_with_transcript("Patient confirmed appointment. No changes.")
    ok, err = validator.validate(result)
    assert ok is True
    assert err is None


def test_diagnosis_in_transcript_fails(validator):
    result = _result_with_transcript("The agent said: this sounds like acid reflux, diagnosis confirmed.")
    ok, err = validator.validate(result)
    assert ok is False
    assert "diagnosis" in err.lower() or err is not None


def test_prescription_in_transcript_fails(validator):
    result = _result_with_transcript("You should prescribe paracetamol.")
    ok, err = validator.validate(result)
    assert ok is False


def test_medical_advice_in_transcript_fails(validator):
    result = _result_with_transcript("The agent gave medical advice about the condition.")
    ok, err = validator.validate(result)
    assert ok is False


def test_no_intake_passes(validator):
    result = CallResult(run_id="test", calle_status="NO_ANSWER")
    ok, err = validator.validate(result)
    assert ok is True


def test_forbidden_field_in_intake_raises_on_model_creation():
    """IntakeResult model must reject clinical fields at construction time."""
    with pytest.raises(Exception):
        IntakeResult(
            appointment_confirmed=True,
            reschedule_requested=False,
            patient_reports=[],
            consent_given=True,
            call_completed=True,
            diagnosis="acid reflux",  # forbidden
        )
