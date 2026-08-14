"""
Integration tests for the handoffs API router.

Tests the full flow:
  POST /appointments (with symptom scenario) → handoff created
  GET  /handoffs/                            → handoff appears in list
  GET  /handoffs/{id}                        → full detail returned
  PATCH /handoffs/{id}/acknowledge           → acknowledged flag set
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from medicall.api import store as app_store
from medicall.api.main import app
from medicall.calle.mock_adapter import MockCallEAdapter
from medicall.engine.coordinator import CoordinationEngine
from medicall.engine.handoff import HandoffGenerator
from medicall.core.models import Appointment, AppointmentSlot


@pytest.fixture(autouse=True)
def clear_store():
    """Reset shared store between tests."""
    app_store.workflows.clear()
    app_store.appointments.clear()
    app_store.handoffs.clear()
    yield
    app_store.workflows.clear()
    app_store.appointments.clear()
    app_store.handoffs.clear()


@pytest.fixture
def client():
    return TestClient(app)


async def _run_scenario(scenario: str) -> str:
    """Run a scenario through the engine, return appointment_id."""
    appt = Appointment(
        patient_name="Test Patient",
        patient_phone="+15550000001",
        clinic_name="Test Clinic",
        appointment_date="2026-08-17",
        appointment_time="10:00",
        language="English",
        alternative_slots=[
            AppointmentSlot(date="2026-08-20", time="14:30", label="Thu 2:30 PM")
        ],
    )
    app_store.appointments[appt.id] = appt
    engine = CoordinationEngine(
        phone_port=MockCallEAdapter(scenario=scenario),
        event_store=app_store.event_store,
        handoff_generator=HandoffGenerator(store=app_store.handoffs),
    )
    record = await engine.run(appt)
    app_store.workflows[record.id] = record
    return appt.id


@pytest.mark.asyncio
async def test_list_handoffs_empty(client):
    resp = client.get("/handoffs/")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_symptom_scenario_creates_handoff(client):
    await _run_scenario("scenario_005_new_symptom")
    resp = client.get("/handoffs/")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["disposition"] == "HUMAN_REVIEW"
    assert data[0]["workflow_action"] == "route_to_nurse_queue"
    assert data[0]["acknowledged"] is False
    assert data[0]["requires_acknowledgment"] is True


@pytest.mark.asyncio
async def test_routine_scenario_no_handoff(client):
    """Routine confirmations do not create handoffs."""
    await _run_scenario("scenario_001_confirm")
    resp = client.get("/handoffs/")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_handoff_detail(client):
    await _run_scenario("scenario_005_new_symptom")
    handoffs = client.get("/handoffs/").json()
    handoff_id = handoffs[0]["id"]

    resp = client.get(f"/handoffs/{handoff_id}")
    assert resp.status_code == 200
    detail = resp.json()

    assert detail["id"] == handoff_id
    assert detail["disposition"] == "HUMAN_REVIEW"
    assert len(detail["patient_reports"]) == 1
    assert "chest pain" in detail["patient_reports"][0]["patient_statement"]
    assert len(detail["evidence"]) == 1
    assert detail["evidence"][0]["call_offset_seconds"] == 42
    assert detail["acknowledged"] is False


@pytest.mark.asyncio
async def test_get_handoff_404(client):
    resp = client.get("/handoffs/nonexistent-id")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_acknowledge_handoff(client):
    await _run_scenario("scenario_005_new_symptom")
    handoffs = client.get("/handoffs/").json()
    handoff_id = handoffs[0]["id"]

    resp = client.patch(
        f"/handoffs/{handoff_id}/acknowledge",
        json={"acknowledged_by": "Nurse Jenkins"},
    )
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["acknowledged"] is True
    assert detail["acknowledged_by"] == "Nurse Jenkins"
    assert detail["acknowledged_at"] is not None


@pytest.mark.asyncio
async def test_acknowledge_idempotent(client):
    """Acknowledging twice updates the record, does not error."""
    await _run_scenario("scenario_005_new_symptom")
    handoff_id = client.get("/handoffs/").json()[0]["id"]

    client.patch(f"/handoffs/{handoff_id}/acknowledge", json={"acknowledged_by": "Dr A"})
    resp = client.patch(
        f"/handoffs/{handoff_id}/acknowledge",
        json={"acknowledged_by": "Dr B"},
    )
    assert resp.status_code == 200
    assert resp.json()["acknowledged_by"] == "Dr B"


@pytest.mark.asyncio
async def test_filter_by_disposition(client):
    await _run_scenario("scenario_005_new_symptom")
    await _run_scenario("scenario_008_escalation")

    human_review = client.get("/handoffs/?disposition=HUMAN_REVIEW").json()
    assert len(human_review) == 2

    routine = client.get("/handoffs/?disposition=ROUTINE").json()
    assert len(routine) == 0


@pytest.mark.asyncio
async def test_pending_only_filter(client):
    await _run_scenario("scenario_005_new_symptom")
    await _run_scenario("scenario_008_escalation")

    all_handoffs = client.get("/handoffs/").json()
    assert len(all_handoffs) == 2

    # Acknowledge one
    client.patch(
        f"/handoffs/{all_handoffs[0]['id']}/acknowledge",
        json={"acknowledged_by": "Staff"},
    )

    pending = client.get("/handoffs/?pending_only=true").json()
    assert len(pending) == 1
    assert pending[0]["id"] == all_handoffs[1]["id"]
