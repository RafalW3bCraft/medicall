"""
Workflow state machine for MediCall.

All state transitions are explicit and deterministic.
No LLM owns workflow state — transitions are driven by
CALL-E result codes and PolicyEngine output only.
"""

from __future__ import annotations

from enum import Enum


class WorkflowState(str, Enum):
    """All possible states of an appointment coordination workflow."""

    CREATED = "CREATED"
    CALL_PENDING = "CALL_PENDING"
    CALLING = "CALLING"
    CONNECTED = "CONNECTED"
    CONSENT_OFFERED = "CONSENT_OFFERED"
    CONSENTED = "CONSENTED"
    INTAKE = "INTAKE"
    VALIDATION = "VALIDATION"
    POLICY_EVALUATION = "POLICY_EVALUATION"
    ROUTINE = "ROUTINE"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    ESCALATION = "ESCALATION"
    NO_ANSWER = "NO_ANSWER"
    RETRY_PENDING = "RETRY_PENDING"
    CONSENT_DECLINED = "CONSENT_DECLINED"
    COMPLETED = "COMPLETED"
    VALIDATION_FAILED = "VALIDATION_FAILED"


# Terminal states — no further transitions possible
TERMINAL_STATES: frozenset[WorkflowState] = frozenset(
    {
        WorkflowState.COMPLETED,
    }
)

# CALL-E terminal statuses (from get_call_run)
CALLE_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {
        "COMPLETED",
        "FAILED",
        "NO_ANSWER",
        "DECLINED",
        "CANCELED",
        "CANCELLED",
        "VOICEMAIL",
        "BUSY",
        "EXPIRED",
    }
)

# Valid transitions: state → set of allowed next states
TRANSITIONS: dict[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.CREATED: frozenset({WorkflowState.CALL_PENDING}),
    WorkflowState.CALL_PENDING: frozenset({WorkflowState.CALLING}),
    WorkflowState.CALLING: frozenset(
        {
            WorkflowState.CONNECTED,
            WorkflowState.NO_ANSWER,
            WorkflowState.CONSENT_DECLINED,  # DECLINED terminal from CALL-E
        }
    ),
    WorkflowState.CONNECTED: frozenset({WorkflowState.CONSENT_OFFERED}),
    WorkflowState.CONSENT_OFFERED: frozenset(
        {WorkflowState.CONSENTED, WorkflowState.CONSENT_DECLINED}
    ),
    WorkflowState.CONSENTED: frozenset({WorkflowState.INTAKE}),
    WorkflowState.INTAKE: frozenset({WorkflowState.VALIDATION}),
    WorkflowState.VALIDATION: frozenset(
        {WorkflowState.POLICY_EVALUATION, WorkflowState.VALIDATION_FAILED}
    ),
    WorkflowState.VALIDATION_FAILED: frozenset({WorkflowState.HUMAN_REVIEW}),
    WorkflowState.POLICY_EVALUATION: frozenset(
        {
            WorkflowState.ROUTINE,
            WorkflowState.HUMAN_REVIEW,
            WorkflowState.ESCALATION,
        }
    ),
    WorkflowState.ROUTINE: frozenset({WorkflowState.COMPLETED}),
    WorkflowState.HUMAN_REVIEW: frozenset({WorkflowState.COMPLETED}),
    WorkflowState.ESCALATION: frozenset({WorkflowState.COMPLETED}),
    WorkflowState.NO_ANSWER: frozenset(
        {WorkflowState.RETRY_PENDING, WorkflowState.COMPLETED}
    ),
    WorkflowState.RETRY_PENDING: frozenset({WorkflowState.CALL_PENDING}),
    WorkflowState.CONSENT_DECLINED: frozenset({WorkflowState.COMPLETED}),
    WorkflowState.COMPLETED: frozenset(),  # terminal
}


def assert_transition(current: WorkflowState, next_state: WorkflowState) -> None:
    """Raise ValueError if the transition current → next_state is not allowed."""
    allowed = TRANSITIONS.get(current, frozenset())
    if next_state not in allowed:
        raise ValueError(
            f"Invalid state transition: {current} → {next_state}. "
            f"Allowed: {sorted(s.value for s in allowed)}"
        )
