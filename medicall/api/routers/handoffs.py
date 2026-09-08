"""
Handoffs router — staff review queue.

GET /handoffs/                  — list all handoffs (filter by disposition)
GET /handoffs/{handoff_id}      — get a single handoff with full detail
PATCH /handoffs/{handoff_id}/acknowledge — staff acknowledges a handoff
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from medicall.api import store as app_store
from medicall.core.models import Handoff

router = APIRouter()


# ── Response models ───────────────────────────────────────────────────────────

class PatientReportOut(BaseModel):
    patient_statement: str
    normalized_description: str
    source: str
    call_offset_seconds: int | None


class EvidenceItemOut(BaseModel):
    rule: str
    patient_statement: str | None
    call_offset_seconds: int | None
    notes: str | None


class HandoffListItem(BaseModel):
    """Compact summary for the queue list view."""
    id: str
    appointment_id: str
    patient_name: str
    appointment_date: str
    appointment_time: str
    disposition: str
    workflow_action: str
    requires_acknowledgment: bool
    acknowledged: bool
    created_at: datetime


class HandoffDetail(BaseModel):
    """Full handoff detail for the staff review card."""
    id: str
    appointment_id: str
    workflow_id: str
    patient_name: str
    appointment_date: str
    appointment_time: str
    disposition: str
    workflow_action: str
    patient_reports: list[PatientReportOut]
    evidence: list[EvidenceItemOut]
    transcript_excerpt: str | None
    requires_acknowledgment: bool
    acknowledged: bool
    acknowledged_at: datetime | None
    acknowledged_by: str | None
    created_at: datetime


class AcknowledgeRequest(BaseModel):
    acknowledged_by: str  # staff member name or ID


# ── In-memory acknowledgement tracking ───────────────────────────────────────
# Keyed by handoff_id. Production would persist this to DB.

_acknowledgements: dict[str, dict] = {}


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/", response_model=list[HandoffListItem])
async def list_handoffs(
    disposition: str | None = Query(
        default=None,
        description="Filter by disposition: ROUTINE | HUMAN_REVIEW | ESCALATION",
    ),
    pending_only: bool = Query(
        default=False,
        description="When true, return only unacknowledged handoffs",
    ),
) -> list[HandoffListItem]:
    """
    List all handoffs, optionally filtered.

    Returns handoffs in reverse-chronological order (newest first).
    Use this as the staff review queue feed.
    """
    items: list[Handoff] = list(app_store.handoffs.values())

    if disposition:
        items = [h for h in items if h.disposition == disposition.upper()]

    if pending_only:
        items = [h for h in items if h.id not in _acknowledgements]

    # Newest first
    items.sort(key=lambda h: h.created_at, reverse=True)

    return [_to_list_item(h) for h in items]


@router.get("/{handoff_id}", response_model=HandoffDetail)
async def get_handoff(handoff_id: str) -> HandoffDetail:
    """
    Get full detail for a single handoff.

    Includes patient-reported information, evidence chain, transcript
    excerpt, and acknowledgement status.
    """
    handoff = app_store.handoffs.get(handoff_id)
    if not handoff:
        raise HTTPException(status_code=404, detail="Handoff not found")
    return _to_detail(handoff)


@router.patch("/{handoff_id}/acknowledge", response_model=HandoffDetail)
async def acknowledge_handoff(
    handoff_id: str,
    body: AcknowledgeRequest,
) -> HandoffDetail:
    """
    Mark a handoff as acknowledged by a staff member.

    Records who acknowledged it and when. Idempotent — acknowledging
    an already-acknowledged handoff updates the timestamp.
    """
    handoff = app_store.handoffs.get(handoff_id)
    if not handoff:
        raise HTTPException(status_code=404, detail="Handoff not found")

    _acknowledgements[handoff_id] = {
        "acknowledged_by": body.acknowledged_by,
        "acknowledged_at": datetime.now(tz=UTC),
    }
    return _to_detail(handoff)


# ── Serialisation helpers ─────────────────────────────────────────────────────

def _to_list_item(h: Handoff) -> HandoffListItem:
    ack = _acknowledgements.get(h.id)
    return HandoffListItem(
        id=h.id,
        appointment_id=h.appointment_id,
        patient_name=h.patient_name,
        appointment_date=h.appointment_date,
        appointment_time=h.appointment_time,
        disposition=h.disposition,
        workflow_action=h.workflow_action,
        requires_acknowledgment=h.requires_acknowledgment,
        acknowledged=ack is not None,
        created_at=h.created_at,
    )


def _to_detail(h: Handoff) -> HandoffDetail:
    ack = _acknowledgements.get(h.id)
    return HandoffDetail(
        id=h.id,
        appointment_id=h.appointment_id,
        workflow_id=h.workflow_id,
        patient_name=h.patient_name,
        appointment_date=h.appointment_date,
        appointment_time=h.appointment_time,
        disposition=h.disposition,
        workflow_action=h.workflow_action,
        patient_reports=[
            PatientReportOut(
                patient_statement=r.patient_statement,
                normalized_description=r.normalized_description,
                source=r.source,
                call_offset_seconds=r.call_offset_seconds,
            )
            for r in h.patient_reports
        ],
        evidence=[
            EvidenceItemOut(
                rule=e.rule,
                patient_statement=e.patient_statement,
                call_offset_seconds=e.call_offset_seconds,
                notes=e.notes,
            )
            for e in h.evidence
        ],
        transcript_excerpt=h.transcript_excerpt,
        requires_acknowledgment=h.requires_acknowledgment,
        acknowledged=ack is not None,
        acknowledged_at=ack["acknowledged_at"] if ack else None,
        acknowledged_by=ack["acknowledged_by"] if ack else None,
        created_at=h.created_at,
    )
