"""
Shared in-memory application state.

Single source of truth for all routers. Replace with a DB-backed
implementation for production.
"""

from __future__ import annotations

from medicall.core.events import InMemoryEventStore
from medicall.core.models import Appointment, Handoff, WorkflowRecord

# Append-only event log
event_store = InMemoryEventStore()

# Keyed by workflow record id
workflows: dict[str, WorkflowRecord] = {}

# Keyed by appointment id
appointments: dict[str, Appointment] = {}

# Keyed by handoff id — populated by CoordinationEngine via HandoffStore
handoffs: dict[str, Handoff] = {}
