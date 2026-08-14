"""
Append-only event store for MediCall.

Events are the source of truth. Current state is derived from the event log.
This gives us: auditability, replay, idempotency, and debugging for free.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class EventType(str, Enum):
    APPOINTMENT_CREATED = "AppointmentCreated"
    CALL_REQUESTED = "CallRequested"
    CALL_STARTED = "CallStarted"
    CALL_COMPLETED = "CallCompleted"
    RESULT_VALIDATED = "ResultValidated"
    VALIDATION_FAILED = "ValidationFailed"
    POLICY_EVALUATED = "PolicyEvaluated"
    HANDOFF_CREATED = "HandoffCreated"
    WORKFLOW_COMPLETED = "WorkflowCompleted"
    RETRY_SCHEDULED = "RetryScheduled"


@dataclass
class Event:
    """An immutable domain event."""

    event_type: EventType
    workflow_id: str
    appointment_id: str
    payload: dict[str, Any]
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    occurred_at: datetime = field(default_factory=datetime.utcnow)


class InMemoryEventStore:
    """
    In-memory event store for development and testing.
    Production should swap this for a SQLite/PostgreSQL-backed store.
    """

    def __init__(self) -> None:
        self._events: list[Event] = []

    def append(self, event: Event) -> None:
        """Append an event. Immutable — no updates or deletes."""
        self._events.append(event)

    def get_for_workflow(self, workflow_id: str) -> list[Event]:
        """Return all events for a workflow, in insertion order."""
        return [e for e in self._events if e.workflow_id == workflow_id]

    def get_for_appointment(self, appointment_id: str) -> list[Event]:
        """Return all events for an appointment, in insertion order."""
        return [e for e in self._events if e.appointment_id == appointment_id]

    def all(self) -> list[Event]:
        return list(self._events)
