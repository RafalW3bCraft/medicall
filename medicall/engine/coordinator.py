"""
CoordinationEngine — orchestrates the full MediCall workflow.

The engine drives state transitions, calls CALL-E via the port,
records events, and delegates to the validator and policy engine.
It never makes clinical decisions — it only coordinates phone work.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from medicall.core.events import Event, EventType, InMemoryEventStore
from medicall.core.idempotency import derive_idempotency_key
from medicall.core.models import (
    Appointment,
    CallTask,
    PolicyDecision,
    WorkflowRecord,
)
from medicall.core.state_machine import WorkflowState, assert_transition
from medicall.engine.handoff import HandoffGenerator
from medicall.engine.policy import PolicyEngine
from medicall.engine.validator import ResultValidator
from medicall.healthcare.goal_builder import build_goal

logger = logging.getLogger(__name__)


class CoordinationEngine:
    """
    Orchestrates a single appointment coordination workflow.

    Responsibilities:
    - Drive WorkflowRecord through state transitions
    - Submit calls via PhoneExecutionPort (real or mock)
    - Record every transition as an event
    - Delegate validation, policy, and handoff to specialized components
    """

    def __init__(
        self,
        phone_port: Any,
        event_store: InMemoryEventStore,
        validator: ResultValidator | None = None,
        policy_engine: PolicyEngine | None = None,
        handoff_generator: HandoffGenerator | None = None,
    ) -> None:
        self.phone_port = phone_port
        self.event_store = event_store
        self.validator = validator or ResultValidator()
        self.policy_engine = policy_engine or PolicyEngine()
        self.handoff_generator = handoff_generator or HandoffGenerator()

    async def run(self, appointment: Appointment) -> WorkflowRecord:
        """
        Execute the full coordination workflow for an appointment.

        Returns the final WorkflowRecord with state=COMPLETED.
        Raises on unrecoverable errors.
        """
        record = WorkflowRecord(
            id=str(uuid.uuid4()),
            appointment_id=appointment.id,
            state=WorkflowState.CREATED,
        )

        self._emit(
            record,
            EventType.APPOINTMENT_CREATED,
            {"appointment_id": appointment.id, "patient_name": appointment.patient_name},
        )

        try:
            record = await self._run_workflow(appointment, record)
        except Exception as exc:
            logger.exception("Workflow failed for appointment=%s", appointment.id)
            record.error = str(exc)
            record.state = WorkflowState.COMPLETED  # terminal even on error

        _print_call_summary(appointment, record)
        return record

    # ─── Internal workflow steps ──────────────────────────────────────────────

    async def _run_workflow(
        self, appointment: Appointment, record: WorkflowRecord
    ) -> WorkflowRecord:
        record = self._transition(record, WorkflowState.CALL_PENDING)

        while record.attempt_number < appointment.max_retry_attempts:
            record.attempt_number += 1
            record = self._transition(record, WorkflowState.CALLING)

            self._emit(
                record,
                EventType.CALL_REQUESTED,
                {"attempt": record.attempt_number},
            )

            task = CallTask(
                appointment_id=appointment.id,
                workflow_id=record.id,
                attempt_number=record.attempt_number,
                phone=appointment.patient_phone,
                goal=build_goal(appointment),
                language=appointment.language,
                region=appointment.region,
                idempotency_key=derive_idempotency_key(
                    record.id, appointment.id, record.attempt_number
                ),
            )

            call_result = await self.phone_port.execute(task)
            record.call_result = call_result

            self._emit(
                record,
                EventType.CALL_COMPLETED,
                {
                    "run_id": call_result.run_id,
                    "calle_status": call_result.calle_status,
                    "attempt": record.attempt_number,
                },
            )

            # Route based on CALL-E terminal status.
            # NO_ANSWER, VOICEMAIL, BUSY, and EXPIRED are all "not reached" outcomes
            # and retry up to max_retry_attempts before flagging for manual follow-up.
            _NOT_REACHED = {"NO_ANSWER", "VOICEMAIL", "BUSY", "EXPIRED"}
            if call_result.calle_status in _NOT_REACHED:
                record = self._transition(record, WorkflowState.NO_ANSWER)
                if record.attempt_number < appointment.max_retry_attempts:
                    record = self._transition(record, WorkflowState.RETRY_PENDING)
                    record = self._transition(record, WorkflowState.CALL_PENDING)
                    continue
                else:
                    # Max retries exhausted — evaluate policy for not-reached
                    decision = self.policy_engine.evaluate(call_result)
                    record.policy_decision = decision
                    self._emit(record, EventType.POLICY_EVALUATED,
                               {"disposition": decision.disposition,
                                "triggered_rules": decision.triggered_rules})
                    break

            if call_result.calle_status in {"DECLINED", "CANCELED", "CANCELLED"}:
                record = self._transition(record, WorkflowState.CONSENT_DECLINED)
                # Evaluate policy for declined/cancelled calls
                decision = self.policy_engine.evaluate(call_result)
                record.policy_decision = decision
                self._emit(record, EventType.POLICY_EVALUATED,
                           {"disposition": decision.disposition,
                            "triggered_rules": decision.triggered_rules})
                break

            # Call connected — proceed through intake
            record = self._transition(record, WorkflowState.CONNECTED)
            record = self._transition(record, WorkflowState.CONSENT_OFFERED)

            if call_result.intake and not call_result.intake.consent_given:
                record = self._transition(record, WorkflowState.CONSENT_DECLINED)
                decision = self.policy_engine.evaluate(call_result)
                record.policy_decision = decision
                self._emit(record, EventType.POLICY_EVALUATED,
                           {"disposition": decision.disposition,
                            "triggered_rules": decision.triggered_rules})
                break

            record = self._transition(record, WorkflowState.CONSENTED)
            record = self._transition(record, WorkflowState.INTAKE)
            record = self._transition(record, WorkflowState.VALIDATION)

            # Validate result
            validation_ok, validation_error = self.validator.validate(call_result)
            if not validation_ok:
                logger.warning(
                    "Result validation failed for appointment=%s: %s",
                    appointment.id,
                    validation_error,
                )
                self._emit(
                    record,
                    EventType.VALIDATION_FAILED,
                    {"error": validation_error},
                )
                record = self._transition(record, WorkflowState.VALIDATION_FAILED)
                record = self._transition(record, WorkflowState.HUMAN_REVIEW)
                # Still produce a policy decision so callers can inspect it
                decision = self.policy_engine.evaluate(call_result)
                record.policy_decision = decision
                self._emit(record, EventType.POLICY_EVALUATED,
                           {"disposition": decision.disposition,
                            "triggered_rules": decision.triggered_rules})
                break

            self._emit(record, EventType.RESULT_VALIDATED, {})

            # Evaluate policy
            record = self._transition(record, WorkflowState.POLICY_EVALUATION)
            decision: PolicyDecision = self.policy_engine.evaluate(call_result)
            record.policy_decision = decision

            self._emit(
                record,
                EventType.POLICY_EVALUATED,
                {
                    "disposition": decision.disposition,
                    "triggered_rules": decision.triggered_rules,
                },
            )

            # Map disposition to state
            disposition_state = {
                "ROUTINE": WorkflowState.ROUTINE,
                "HUMAN_REVIEW": WorkflowState.HUMAN_REVIEW,
                "ESCALATION": WorkflowState.ESCALATION,
            }.get(decision.disposition, WorkflowState.HUMAN_REVIEW)

            record = self._transition(record, disposition_state)

            # Generate handoff if needed
            if decision.disposition in {"HUMAN_REVIEW", "ESCALATION"}:
                handoff = self.handoff_generator.generate(appointment, record)
                record.handoff_id = handoff.id
                self._emit(
                    record,
                    EventType.HANDOFF_CREATED,
                    {"handoff_id": handoff.id, "disposition": decision.disposition},
                )

            break  # Successful call — exit retry loop

        # Complete workflow
        record = self._transition(record, WorkflowState.COMPLETED)
        self._emit(record, EventType.WORKFLOW_COMPLETED, {"state": record.state.value})
        return record

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def _transition(
        self, record: WorkflowRecord, next_state: WorkflowState
    ) -> WorkflowRecord:
        assert_transition(record.state, next_state)
        logger.debug(
            "Transition: appointment=%s %s → %s",
            record.appointment_id,
            record.state,
            next_state,
        )
        record.state = next_state
        return record

    def _emit(
        self, record: WorkflowRecord, event_type: EventType, payload: dict
    ) -> None:
        self.event_store.append(
            Event(
                event_type=event_type,
                workflow_id=record.id,
                appointment_id=record.appointment_id,
                payload=payload,
            )
        )


# ── Console call summary ───────────────────────────────────────────────────────

def _print_call_summary(appointment: Appointment, record: WorkflowRecord) -> None:
    """
    Print a structured summary of a completed coordination workflow to stdout.

    Emitted once after every engine.run() — for both the API server and the
    eval harness — so operators can trace the full outcome at a glance without
    digging through logs.
    """
    decision = record.policy_decision
    call_result = record.call_result

    run_id = call_result.run_id if call_result else "—"
    calle_status = call_result.calle_status if call_result else "—"
    disposition = decision.disposition if decision else "—"
    action = decision.workflow_action if decision else "—"
    handoff = record.handoff_id or "—"
    error = record.error or "—"

    divider = "─" * 56
    print(f"\n{divider}", flush=True)
    print("  MediCall — Call Interaction Summary", flush=True)
    print(divider, flush=True)
    print(f"  Patient:     {appointment.patient_name}  ({appointment.patient_phone})", flush=True)
    print(f"  Clinic:      {appointment.clinic_name}", flush=True)
    appt_when = f"{appointment.appointment_date} at {appointment.appointment_time}"
    print(f"  Appointment: {appt_when}", flush=True)
    print(f"  run_id:      {run_id}", flush=True)
    print(f"  CALL-E:      {calle_status}", flush=True)
    print(f"  Attempts:    {record.attempt_number}", flush=True)
    print(f"  Disposition: {disposition}", flush=True)
    print(f"  Action:      {action}", flush=True)
    print(f"  Handoff:     {handoff}", flush=True)
    if record.error:
        print(f"  Error:       {error}", flush=True)
    print(divider, flush=True)
    print("", flush=True)
