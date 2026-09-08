"""
Domain models for MediCall.

All models use Pydantic v2 for runtime validation.
Forbidden fields (diagnosis, clinical_recommendation, etc.) are
enforced at the schema level — they must never appear in any result.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from medicall.core.state_machine import WorkflowState

# ─── Appointment ──────────────────────────────────────────────────────────────

class AppointmentSlot(BaseModel):
    """An alternative appointment slot offered during rescheduling."""

    date: str  # ISO date string e.g. "2026-09-01"
    time: str  # HH:MM e.g. "14:30"
    label: str  # human-readable e.g. "Monday 1 Sep at 2:30 PM"


class Appointment(BaseModel):
    """An appointment record to be coordinated via CALL-E."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    patient_name: str
    patient_phone: str  # E.164 format e.g. "+15551234567"
    clinic_name: str
    appointment_date: str  # ISO date e.g. "2026-09-01"
    appointment_time: str  # HH:MM e.g. "10:00"
    language: str = "English"
    region: str | None = None
    alternative_slots: list[AppointmentSlot] = Field(default_factory=list)
    max_retry_attempts: int = 3
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ─── CALL-E task / result ─────────────────────────────────────────────────────

class CallTask(BaseModel):
    """Parameters passed to the PhoneExecutionPort."""

    appointment_id: str
    workflow_id: str
    attempt_number: int
    phone: str
    goal: str
    language: str
    region: str | None = None
    idempotency_key: str


class PatientReport(BaseModel):
    """A single patient-reported item captured during the call."""

    patient_statement: str
    normalized_description: str
    source: str = "patient"
    call_offset_seconds: int | None = None

    @field_validator("patient_statement", "normalized_description")
    @classmethod
    def no_clinical_language(cls, v: str) -> str:
        """Reject values that contain forbidden clinical language."""
        forbidden = [
            "diagnosis",
            "diagnose",
            "prescribe",
            "prescription",
            "treatment recommendation",
            "clinical conclusion",
            "medical advice",
        ]
        lower = v.lower()
        for word in forbidden:
            if word in lower:
                raise ValueError(
                    f"Patient report contains forbidden clinical language: '{word}'. "
                    "MediCall records patient statements only — it does not diagnose."
                )
        return v


class IntakeResult(BaseModel):
    """
    Structured result extracted from a CALL-E call.

    INVARIANT: This model must NEVER contain a diagnosis, clinical
    recommendation, severity assessment, or medical advice field.
    Any attempt to set such fields will raise a validation error.
    """

    appointment_confirmed: bool
    reschedule_requested: bool
    rescheduled_to: AppointmentSlot | None = None
    patient_reports: list[PatientReport] = Field(default_factory=list)
    consent_given: bool
    call_completed: bool

    @model_validator(mode="before")
    @classmethod
    def reject_clinical_fields(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Hard reject if the raw dict contains any forbidden clinical keys."""
        forbidden_keys = {
            "diagnosis",
            "diagnoses",
            "severity_assessment",
            "clinical_recommendation",
            "treatment_suggestion",
            "medical_advice",
            "prognosis",
        }
        present = forbidden_keys & set(values.keys())
        if present:
            raise ValueError(
                f"IntakeResult contains forbidden clinical fields: {present}. "
                "MediCall is not a diagnostic system."
            )
        return values


class CallResult(BaseModel):
    """Raw result returned by the PhoneExecutionPort after CALL-E completes."""

    run_id: str
    calle_status: str  # COMPLETED, NO_ANSWER, DECLINED, etc.
    intake: IntakeResult | None = None
    transcript: str | None = None
    # CALL-E returns evidence as list[str] (human-readable strings).
    # Typed as list[str | dict] to handle both current and future formats.
    evidence: list[str | dict[str, Any]] = Field(default_factory=list)
    call_id: str | None = None
    duration_seconds: int | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    raw_calle_response: dict[str, Any] = Field(default_factory=dict)


# ─── Policy output ────────────────────────────────────────────────────────────

class Disposition(str):
    ROUTINE = "ROUTINE"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    ESCALATION = "ESCALATION"


class EvidenceItem(BaseModel):
    """A single piece of evidence linking a policy rule to call data."""

    rule: str
    patient_statement: str | None = None
    call_offset_seconds: int | None = None
    notes: str | None = None


class PolicyDecision(BaseModel):
    """Output of the PolicyEngine — a deterministic workflow disposition."""

    disposition: str  # ROUTINE | HUMAN_REVIEW | ESCALATION
    triggered_rules: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    workflow_action: str  # e.g. "routine_complete", "route_to_nurse_queue"


# ─── Handoff ──────────────────────────────────────────────────────────────────

class Handoff(BaseModel):
    """
    Human-review handoff package produced after policy evaluation.

    This is what a clinic staff member sees in their queue.
    It contains no diagnosis — only structured patient-reported information,
    provenance evidence, and the deterministic workflow disposition.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    appointment_id: str
    workflow_id: str
    patient_name: str
    appointment_date: str
    appointment_time: str
    disposition: str
    workflow_action: str
    patient_reports: list[PatientReport]
    evidence: list[EvidenceItem]
    transcript_excerpt: str | None = None
    requires_acknowledgment: bool
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ─── Workflow record ──────────────────────────────────────────────────────────

class WorkflowRecord(BaseModel):
    """Persisted state of a single coordination workflow run."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    appointment_id: str
    state: WorkflowState = WorkflowState.CREATED
    attempt_number: int = 0
    call_result: CallResult | None = None
    policy_decision: PolicyDecision | None = None
    handoff_id: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
