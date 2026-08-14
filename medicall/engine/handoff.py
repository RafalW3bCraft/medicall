"""
HandoffGenerator — produces human-review handoff packages.

A Handoff is the artefact that a clinic staff member sees in their queue.
It contains no clinical conclusions — only structured patient-reported
information, provenance evidence, and the deterministic workflow disposition.
"""

from __future__ import annotations

from medicall.core.models import Appointment, Handoff, WorkflowRecord


class HandoffGenerator:
    """Generates a Handoff from a completed WorkflowRecord."""

    def generate(self, appointment: Appointment, record: WorkflowRecord) -> Handoff:
        """Build a Handoff for staff review."""
        decision = record.policy_decision
        call_result = record.call_result

        patient_reports = []
        transcript_excerpt = None

        if call_result and call_result.intake:
            patient_reports = call_result.intake.patient_reports

        if call_result and call_result.transcript:
            # Show only first 500 chars in the handoff — full transcript in audit log
            transcript_excerpt = call_result.transcript[:500]

        evidence = decision.evidence if decision else []
        disposition = decision.disposition if decision else "HUMAN_REVIEW"
        workflow_action = decision.workflow_action if decision else "route_to_nurse_queue"

        return Handoff(
            appointment_id=appointment.id,
            workflow_id=record.id,
            patient_name=appointment.patient_name,
            appointment_date=appointment.appointment_date,
            appointment_time=appointment.appointment_time,
            disposition=disposition,
            workflow_action=workflow_action,
            patient_reports=patient_reports,
            evidence=evidence,
            transcript_excerpt=transcript_excerpt,
            requires_acknowledgment=(disposition in {"HUMAN_REVIEW", "ESCALATION"}),
        )
