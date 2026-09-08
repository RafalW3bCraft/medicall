"""Tests for the WorkflowState state machine."""
from __future__ import annotations

import pytest

from medicall.core.state_machine import TERMINAL_STATES, WorkflowState, assert_transition


def test_valid_transition_created_to_call_pending():
    assert_transition(WorkflowState.CREATED, WorkflowState.CALL_PENDING)


def test_valid_transition_call_pending_to_calling():
    assert_transition(WorkflowState.CALL_PENDING, WorkflowState.CALLING)


def test_valid_transition_policy_to_routine():
    assert_transition(WorkflowState.POLICY_EVALUATION, WorkflowState.ROUTINE)


def test_valid_transition_policy_to_human_review():
    assert_transition(WorkflowState.POLICY_EVALUATION, WorkflowState.HUMAN_REVIEW)


def test_valid_transition_policy_to_escalation():
    assert_transition(WorkflowState.POLICY_EVALUATION, WorkflowState.ESCALATION)


def test_valid_transition_no_answer_to_retry():
    assert_transition(WorkflowState.NO_ANSWER, WorkflowState.RETRY_PENDING)


def test_valid_transition_no_answer_to_completed():
    assert_transition(WorkflowState.NO_ANSWER, WorkflowState.COMPLETED)


def test_invalid_transition_raises():
    with pytest.raises(ValueError, match="Invalid state transition"):
        assert_transition(WorkflowState.CREATED, WorkflowState.COMPLETED)


def test_invalid_transition_backwards():
    with pytest.raises(ValueError, match="Invalid state transition"):
        assert_transition(WorkflowState.COMPLETED, WorkflowState.CREATED)


def test_completed_is_terminal():
    assert WorkflowState.COMPLETED in TERMINAL_STATES


def test_non_terminal_states_not_in_terminal_set():
    non_terminal = [
        WorkflowState.CREATED,
        WorkflowState.CALLING,
        WorkflowState.HUMAN_REVIEW,
    ]
    for state in non_terminal:
        assert state not in TERMINAL_STATES
