"""
Eval harness — runs all 10 acceptance scenarios and prints a pass/fail table.

Usage:
    python -m eval.run_eval
    # or from repo root:
    cd medicall && python -m eval.run_eval
"""

from __future__ import annotations

import asyncio
import sys
import traceback
from dataclasses import dataclass

from medicall.calle.mock_adapter import MockCallEAdapter
from medicall.core.events import InMemoryEventStore
from medicall.core.models import Appointment, AppointmentSlot
from medicall.core.state_machine import WorkflowState
from medicall.engine.coordinator import CoordinationEngine


@dataclass
class EvalCase:
    name: str
    scenario: str
    max_retries: int = 3
    expected_disposition: str | None = None
    expected_state: str = "COMPLETED"
    check_no_diagnosis: bool = False
    check_handoff: bool = False
    check_evidence: bool = False
    check_no_patient_reports: bool = False


EVAL_CASES: list[EvalCase] = [
    EvalCase(
        name="001 — Confirm",
        scenario="scenario_001_confirm",
        expected_disposition="ROUTINE",
    ),
    EvalCase(
        name="002 — Reschedule",
        scenario="scenario_002_reschedule",
        expected_disposition="ROUTINE",
    ),
    EvalCase(
        name="003 — No answer (1 attempt)",
        scenario="scenario_003_no_answer",
        max_retries=1,
        expected_disposition="ROUTINE",
    ),
    EvalCase(
        name="004 — Consent declined",
        scenario="scenario_004_consent_declined",
        expected_disposition="ROUTINE",
        check_no_patient_reports=True,
    ),
    EvalCase(
        name="005 — New symptom → HUMAN_REVIEW",
        scenario="scenario_005_new_symptom",
        expected_disposition="HUMAN_REVIEW",
        check_evidence=True,
        check_handoff=True,
    ),
    EvalCase(
        name="006 — Ambiguous response → HUMAN_REVIEW",
        scenario="scenario_006_ambiguous",
        expected_disposition="HUMAN_REVIEW",
    ),
    EvalCase(
        name="007 — Medical advice boundary",
        scenario="scenario_007_medical_advice_boundary",
        check_no_diagnosis=True,
    ),
    EvalCase(
        name="008 — Escalation path → HUMAN_REVIEW + handoff",
        scenario="scenario_008_escalation",
        expected_disposition="HUMAN_REVIEW",
        check_handoff=True,
    ),
    EvalCase(
        name="009 — Idempotency (2 runs → 2 distinct keys)",
        scenario="scenario_001_confirm",
    ),
    EvalCase(
        name="010 — Max retries (3 NO_ANSWER → COMPLETED)",
        scenario="scenario_003_no_answer",
        max_retries=3,
    ),
]


def _make_appointment(max_retries: int = 3) -> Appointment:
    return Appointment(
        patient_name="Eval Patient",
        patient_phone="+15550000099",
        clinic_name="Eval Clinic",
        appointment_date="2026-08-17",
        appointment_time="10:00",
        language="English",
        alternative_slots=[
            AppointmentSlot(date="2026-08-20", time="14:30", label="Thu 20 Aug 2:30 PM")
        ],
        max_retry_attempts=max_retries,
    )


async def run_case(case: EvalCase) -> tuple[bool, str]:
    try:
        mock = MockCallEAdapter(scenario=case.scenario)
        store = InMemoryEventStore()
        engine = CoordinationEngine(phone_port=mock, event_store=store)
        appt = _make_appointment(case.max_retries)

        # Special case: idempotency test runs engine twice
        if "Idempotency" in case.name:
            r1 = await engine.run(appt)
            r2 = await engine.run(appt)
            assert r1.id != r2.id, "Workflow IDs must be distinct"
            assert mock.call_count == 2, f"Expected 2 CALL-E calls, got {mock.call_count}"
            return True, "PASS"

        # Special case: max retries
        if "Max retries" in case.name:
            record = await engine.run(appt)
            assert mock.call_count == 3, f"Expected 3 calls, got {mock.call_count}"
            assert record.state == WorkflowState.COMPLETED
            return True, "PASS"

        record = await engine.run(appt)

        assert record.state.value == case.expected_state, (
            f"State: expected {case.expected_state}, got {record.state.value}"
        )

        if case.expected_disposition:
            actual = record.policy_decision.disposition if record.policy_decision else None
            assert actual == case.expected_disposition, (
                f"Disposition: expected {case.expected_disposition}, got {actual}"
            )

        if case.check_evidence:
            assert record.policy_decision and len(record.policy_decision.evidence) > 0, (
                "Expected evidence items in policy decision"
            )

        if case.check_handoff:
            assert record.handoff_id is not None, "Expected handoff_id to be set"

        if case.check_no_patient_reports:
            assert record.call_result and record.call_result.intake
            assert record.call_result.intake.patient_reports == [], (
                "Expected no patient reports when consent declined"
            )

        if case.check_no_diagnosis:
            intake = record.call_result and record.call_result.intake
            assert intake is None or not hasattr(intake, "diagnosis"), (
                "diagnosis field must never appear in intake"
            )

        return True, "PASS"

    except Exception as exc:
        return False, f"FAIL — {exc}"


async def main() -> None:
    col_name = 42
    col_result = 10

    header = f"{'Scenario':<{col_name}}  {'Result':<{col_result}}"
    divider = "─" * len(header)
    print()
    print("MediCall Eval Harness")
    print(divider)
    print(header)
    print(divider)

    passed = 0
    failed = 0

    for case in EVAL_CASES:
        ok, label = await run_case(case)
        marker = "✓" if ok else "✗"
        print(f"{marker}  {case.name:<{col_name - 3}} {label:<{col_result}}")
        if ok:
            passed += 1
        else:
            failed += 1

    print(divider)
    print(f"  {passed} passed, {failed} failed")
    print()

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
