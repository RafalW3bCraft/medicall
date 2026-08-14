"""
Appointments router.

POST /appointments  — create an appointment and trigger coordination workflow
GET  /appointments/{id} — get workflow status and result
"""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from medicall.calle.mock_adapter import MockCallEAdapter
from medicall.calle.real_adapter import RealCallEAdapter
from medicall.core.events import InMemoryEventStore
from medicall.core.models import Appointment, AppointmentSlot, WorkflowRecord
from medicall.engine.coordinator import CoordinationEngine

router = APIRouter()

# Shared in-memory store (replace with DB-backed store for production)
_event_store = InMemoryEventStore()
_workflows: dict[str, WorkflowRecord] = {}
_appointments: dict[str, Appointment] = {}


def _get_phone_port():
    use_mock = os.getenv("USE_MOCK_CALLE", "true").lower() == "true"
    if use_mock:
        scenario = os.getenv("MOCK_SCENARIO", "scenario_001_confirm")
        return MockCallEAdapter(scenario=scenario)
    return RealCallEAdapter()


class AppointmentRequest(BaseModel):
    patient_name: str
    patient_phone: str
    clinic_name: str
    appointment_date: str
    appointment_time: str
    language: str = "English"
    region: str | None = None
    alternative_slots: list[AppointmentSlot] = []
    max_retry_attempts: int = 3


class WorkflowStatusResponse(BaseModel):
    appointment_id: str
    workflow_id: str
    state: str
    attempt_number: int
    disposition: str | None
    workflow_action: str | None
    handoff_id: str | None
    error: str | None


@router.post("/", response_model=WorkflowStatusResponse, status_code=201)
async def create_appointment(body: AppointmentRequest) -> WorkflowStatusResponse:
    """Create an appointment record and immediately run the coordination workflow."""
    appointment = Appointment(**body.model_dump())
    _appointments[appointment.id] = appointment

    engine = CoordinationEngine(
        phone_port=_get_phone_port(),
        event_store=_event_store,
    )

    record = await engine.run(appointment)
    _workflows[record.id] = record

    return _to_response(appointment.id, record)


@router.get("/{appointment_id}", response_model=WorkflowStatusResponse)
async def get_appointment_status(appointment_id: str) -> WorkflowStatusResponse:
    """Get the latest workflow status for an appointment."""
    record = next(
        (r for r in _workflows.values() if r.appointment_id == appointment_id),
        None,
    )
    if not record:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return _to_response(appointment_id, record)


def _to_response(appointment_id: str, record: WorkflowRecord) -> WorkflowStatusResponse:
    decision = record.policy_decision
    return WorkflowStatusResponse(
        appointment_id=appointment_id,
        workflow_id=record.id,
        state=record.state.value,
        attempt_number=record.attempt_number,
        disposition=decision.disposition if decision else None,
        workflow_action=decision.workflow_action if decision else None,
        handoff_id=record.handoff_id,
        error=record.error,
    )
