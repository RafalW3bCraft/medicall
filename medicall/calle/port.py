"""
PhoneExecutionPort — the abstraction boundary between MediCall and CALL-E.

Both the real CALL-E adapter and the mock adapter implement this Protocol.
The CoordinationEngine depends only on this protocol, never on the concrete
implementations, so tests never burn real CALL-E credits.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from medicall.core.models import CallResult, CallTask


@runtime_checkable
class PhoneExecutionPort(Protocol):
    """Abstract port for phone call execution."""

    async def execute(self, task: CallTask) -> CallResult:
        """
        Execute a phone call task and return the final result.

        Implementations must:
        - Submit the call using the task's idempotency_key to prevent duplicates
        - Poll until a terminal CALL-E status is reached
        - Parse the terminal response into a CallResult

        Must NOT:
        - Place a call if one already exists for the same idempotency_key
        - Raise on NO_ANSWER or DECLINED — these are valid terminal states
        """
        ...
