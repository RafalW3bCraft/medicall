"""
MediCall Eval / Batch Runner

Two modes:

  1. Scenario smoke-test (default — no CSV):
       cd medicall && python -m eval.run_eval
     Runs all 8 recorded scenarios through RecordedCallEAdapter → pass/fail table.

  2. Live CSV batch runner:
       cd medicall && python -m eval.run_eval --csv path/to/appointments.json
     Reads a JSON file of appointment dicts, calls each patient via
     RealCallEAdapter, and prints live console activity for every call.

CSV / JSON file format (same as examples/appointments.example.json):
    [
      {
        "patient_name": "Jane Smith",
        "patient_phone": "+15551234567",
        "clinic_name": "City Medical Centre",
        "appointment_date": "2026-09-01",
        "appointment_time": "10:00",
        "language": "English",
        "region": "IN",
        "alternative_slots": [...],
        "max_retry_attempts": 3
      },
      ...
    ]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path

from medicall.calle.real_adapter import RealCallEAdapter
from medicall.calle.recorded_adapter import RecordedCallEAdapter
from medicall.core.events import InMemoryEventStore
from medicall.core.models import Appointment, AppointmentSlot
from medicall.core.state_machine import WorkflowState
from medicall.engine.coordinator import CoordinationEngine
from medicall.engine.handoff import HandoffGenerator

# ── Smoke-test scenarios ───────────────────────────────────────────────────────

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
    EvalCase(
        name="011 — Voicemail → flag_for_manual_followup",
        scenario="scenario_003b_voicemail",
        max_retries=1,
        expected_disposition="ROUTINE",
    ),
]


def _make_test_appointment(max_retries: int = 3) -> Appointment:
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


async def _run_smoke_case(case: EvalCase) -> tuple[bool, str]:
    try:
        adapter = RecordedCallEAdapter(scenario=case.scenario)
        store = InMemoryEventStore()
        engine = CoordinationEngine(phone_port=adapter, event_store=store)
        appt = _make_test_appointment(case.max_retries)

        # Special case: idempotency test runs engine twice
        if "Idempotency" in case.name:
            r1 = await engine.run(appt)
            r2 = await engine.run(appt)
            assert r1.id != r2.id, "Workflow IDs must be distinct"
            assert adapter.call_count == 2, f"Expected 2 calls, got {adapter.call_count}"
            return True, "PASS"

        # Special case: max retries
        if "Max retries" in case.name:
            record = await engine.run(appt)
            assert adapter.call_count == 3, f"Expected 3 calls, got {adapter.call_count}"
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


async def _smoke_test() -> None:
    """Run all recorded scenarios and print pass/fail table."""
    col_name = 42
    col_result = 10

    header = f"{'Scenario':<{col_name}}  {'Result':<{col_result}}"
    divider = "─" * len(header)
    print()
    print("MediCall Eval Harness — Smoke Test (recorded scenarios)")
    print(divider)
    print(header)
    print(divider)

    passed = 0
    failed = 0

    for case in EVAL_CASES:
        ok, label = await _run_smoke_case(case)
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


# ── Live CSV batch runner ──────────────────────────────────────────────────────

def _load_appointments(path: str) -> list[Appointment]:
    """Load appointments from a JSON file (list of appointment dicts)."""
    data = json.loads(Path(path).read_text())
    if not isinstance(data, list):
        raise ValueError(f"Expected a JSON array in {path}, got {type(data).__name__}")

    appointments = []
    for i, row in enumerate(data):
        try:
            # Convert alternative_slots dicts → AppointmentSlot objects
            raw_slots = row.pop("alternative_slots", [])
            slots = [AppointmentSlot(**s) for s in raw_slots]
            appt = Appointment(**row, alternative_slots=slots)
            appointments.append(appt)
        except Exception as exc:
            raise ValueError(f"Row {i + 1} in {path} is invalid: {exc}") from exc

    return appointments


async def _run_live_batch(csv_path: str) -> None:
    """Load appointments from JSON and call each via RealCallEAdapter."""
    appointments = _load_appointments(csv_path)
    total = len(appointments)

    print()
    print(f"MediCall Batch Runner — {total} appointment(s) from {csv_path}")
    print("=" * 60)

    results: list[tuple[str, str, str]] = []  # (patient_name, status, disposition)

    for idx, appt in enumerate(appointments, start=1):
        print(f"\n[{idx}/{total}] {appt.patient_name}  {appt.patient_phone}")
        print(f"     Clinic: {appt.clinic_name}  "
              f"Appointment: {appt.appointment_date} {appt.appointment_time}")
        print("─" * 60)

        try:
            adapter = RealCallEAdapter()
            handoffs: dict = {}
            store = InMemoryEventStore()
            engine = CoordinationEngine(
                phone_port=adapter,
                event_store=store,
                handoff_generator=HandoffGenerator(store=handoffs),
            )

            record = await engine.run(appt)

            disposition = (
                record.policy_decision.disposition
                if record.policy_decision
                else "UNKNOWN"
            )
            action = (
                record.policy_decision.workflow_action
                if record.policy_decision
                else "—"
            )
            calle_status = (
                record.call_result.calle_status if record.call_result else "—"
            )

            print(f"   State:       {record.state.value}")
            print(f"   CALL-E:      {calle_status}")
            print(f"   Disposition: {disposition}")
            print(f"   Action:      {action}")
            if record.handoff_id:
                print(f"   Handoff:     {record.handoff_id}")
            if record.error:
                print(f"   Error:       {record.error}")

            results.append((appt.patient_name, calle_status, disposition))

        except Exception as exc:
            print(f"   ERROR: {exc}")
            traceback.print_exc()
            results.append((appt.patient_name, "ERROR", str(exc)[:60]))

    # Summary table
    print()
    print("=" * 60)
    print("Batch Summary")
    print("─" * 60)
    col_w = 22
    print(f"  {'Patient':<{col_w}}  {'CALL-E':<12}  Disposition")
    print(f"  {'─' * col_w}  {'─' * 12}  {'─' * 12}")
    for name, status, dispo in results:
        print(f"  {name:<{col_w}}  {status:<12}  {dispo}")
    print()


# ── Entry point ────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m eval.run_eval",
        description="MediCall eval harness — smoke test or live batch runner",
    )
    parser.add_argument(
        "--csv",
        metavar="PATH",
        default=None,
        help=(
            "Path to a JSON file containing a list of appointment dicts. "
            "When provided, runs live CALL-E calls via RealCallEAdapter. "
            "Without this flag, runs the recorded smoke-test scenarios."
        ),
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    if args.csv:
        asyncio.run(_run_live_batch(args.csv))
    else:
        asyncio.run(_smoke_test())
