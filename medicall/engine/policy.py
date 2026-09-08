"""
PolicyEngine — deterministic workflow disposition from a CallResult.

D = f(R, C, P)
  R = reported information (CallResult)
  C = workflow context
  P = predefined policy rules
  D = operational disposition (ROUTINE | HUMAN_REVIEW | ESCALATION)

INVARIANT: D is never a clinical diagnosis. It is always an operational
decision about which human workflow should happen next.

Rules are evaluated in priority order — first match wins.
"""

from __future__ import annotations

import logging

from medicall.core.models import CallResult, EvidenceItem, PolicyDecision

logger = logging.getLogger(__name__)


class PolicyEngine:
    """
    Evaluates a validated CallResult against deterministic policy rules.

    Each rule is a method prefixed with _rule_. Rules are tried in
    definition order (priority). The first matching rule determines the
    disposition.
    """

    def evaluate(self, result: CallResult) -> PolicyDecision:
        """Evaluate all rules and return the first matching disposition."""
        for rule_fn in self._rule_pipeline():
            decision = rule_fn(result)
            if decision is not None:
                logger.debug(
                    "Policy rule matched: rules=%s disposition=%s",
                    decision.triggered_rules,
                    decision.disposition,
                )
                return decision

        # Default: routine (should not reach here if rules are complete)
        return PolicyDecision(
            disposition="ROUTINE",
            triggered_rules=["default_fallback"],
            evidence=[],
            workflow_action="routine_complete",
        )

    # ─── Rule pipeline ────────────────────────────────────────────────────────

    def _rule_pipeline(self):
        """Return rules in priority order."""
        return [
            self._r03_new_symptom_reported,      # highest priority
            self._r07_validation_failed,
            self._r02_reschedule_requested,
            self._r04_consent_declined,
            self._r06_no_answer_max_attempts,
            self._r01_confirmed_no_reports,      # lowest priority catch-all
        ]

    # R01 — Appointment confirmed, no patient reports
    def _r01_confirmed_no_reports(self, result: CallResult) -> PolicyDecision | None:
        if (
            result.intake
            and result.intake.appointment_confirmed
            and not result.intake.patient_reports
        ):
            return PolicyDecision(
                disposition="ROUTINE",
                triggered_rules=["R01_confirmed_no_reports"],
                evidence=[],
                workflow_action="routine_complete",
            )
        return None

    # R02 — Reschedule requested and new slot provided
    def _r02_reschedule_requested(self, result: CallResult) -> PolicyDecision | None:
        if result.intake and result.intake.reschedule_requested:
            if result.intake.rescheduled_to:
                return PolicyDecision(
                    disposition="ROUTINE",
                    triggered_rules=["R02_reschedule_confirmed"],
                    evidence=[],
                    workflow_action="update_appointment_slot",
                )
            else:
                return PolicyDecision(
                    disposition="HUMAN_REVIEW",
                    triggered_rules=["R02_reschedule_no_slot"],
                    evidence=[],
                    workflow_action="route_to_reception_queue",
                )
        return None

    # R03 — Any patient report raises HUMAN_REVIEW (highest priority)
    def _r03_new_symptom_reported(self, result: CallResult) -> PolicyDecision | None:
        if result.intake and result.intake.patient_reports:
            evidence = [
                EvidenceItem(
                    rule="R03_new_symptom_reported",
                    patient_statement=r.patient_statement,
                    call_offset_seconds=r.call_offset_seconds,
                )
                for r in result.intake.patient_reports
            ]
            return PolicyDecision(
                disposition="HUMAN_REVIEW",
                triggered_rules=["R03_new_symptom_reported"],
                evidence=evidence,
                workflow_action="route_to_nurse_queue",
            )
        return None

    # R04 — Consent declined: no intake data, routine close
    def _r04_consent_declined(self, result: CallResult) -> PolicyDecision | None:
        if result.intake and not result.intake.consent_given:
            return PolicyDecision(
                disposition="ROUTINE",
                triggered_rules=["R04_consent_declined"],
                evidence=[],
                workflow_action="document_consent_decline",
            )
        return None

    # R06 — Not reached after max attempts (NO_ANSWER, VOICEMAIL, BUSY, EXPIRED all retry
    #        and reach this rule only when max_retry_attempts is exhausted)
    def _r06_no_answer_max_attempts(self, result: CallResult) -> PolicyDecision | None:
        _NOT_REACHED = {"NO_ANSWER", "VOICEMAIL", "BUSY", "EXPIRED"}
        if result.calle_status in _NOT_REACHED:
            return PolicyDecision(
                disposition="ROUTINE",
                triggered_rules=["R06_no_answer_max_attempts"],
                evidence=[],
                workflow_action="flag_for_manual_followup",
            )
        return None

    # R07 — Validation failed (called from engine before policy, but kept as fallback)
    def _r07_validation_failed(self, result: CallResult) -> PolicyDecision | None:
        # This rule normally fires from the engine's validation branch.
        # Included here as a safety net if policy is called with a bad result.
        if result.calle_status == "FAILED":
            return PolicyDecision(
                disposition="HUMAN_REVIEW",
                triggered_rules=["R07_call_failed"],
                evidence=[],
                workflow_action="route_to_nurse_queue",
            )
        return None
