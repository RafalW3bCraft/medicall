"""
MockCallEAdapter — replays recorded scenarios without placing real calls.

All development and unit/integration tests must use this adapter.
Real CALL-E credits are reserved for acceptance testing and the demo only.

Usage:
    adapter = MockCallEAdapter(scenario="scenario_005_new_symptom")
    result = await adapter.execute(task)

Scenarios are loaded from tests/scenarios/*.json.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from medicall.core.models import (
    AppointmentSlot,
    CallResult,
    CallTask,
    IntakeResult,
    PatientReport,
)

logger = logging.getLogger(__name__)

SCENARIOS_DIR = Path(__file__).parent.parent.parent / "tests" / "scenarios"


class MockCallEAdapter:
    """
    Replay-based mock adapter for testing without real CALL-E calls.

    Loads a scenario JSON fixture and returns a pre-built CallResult.
    Simulates realistic async latency (configurable).
    """

    def __init__(
        self,
        scenario: str = "scenario_001_confirm",
        simulate_latency_seconds: float = 0.05,
    ) -> None:
        self.scenario = scenario
        self.simulate_latency_seconds = simulate_latency_seconds
        self._call_count: int = 0

    @property
    def call_count(self) -> int:
        """Number of times execute() has been called. Used in idempotency tests."""
        return self._call_count

    async def execute(self, task: CallTask) -> CallResult:
        """Return a pre-built CallResult from the named scenario fixture."""
        self._call_count += 1
        await asyncio.sleep(self.simulate_latency_seconds)

        scenario_path = SCENARIOS_DIR / f"{self.scenario}.json"
        if not scenario_path.exists():
            raise FileNotFoundError(
                f"Scenario fixture not found: {scenario_path}. "
                f"Available: {[p.stem for p in SCENARIOS_DIR.glob('*.json')]}"
            )

        raw = json.loads(scenario_path.read_text())
        logger.debug(
            "MockCallEAdapter replaying scenario=%s for appointment=%s",
            self.scenario,
            task.appointment_id,
        )
        return self._deserialize(raw)

    @staticmethod
    def _deserialize(raw: dict) -> CallResult:
        """Deserialize a scenario fixture dict into a CallResult."""
        intake_raw = raw.get("intake")
        intake = None
        if intake_raw:
            reports = [
                PatientReport(**r) for r in intake_raw.get("patient_reports", [])
            ]
            rescheduled_to = None
            if intake_raw.get("rescheduled_to"):
                rescheduled_to = AppointmentSlot(**intake_raw["rescheduled_to"])
            intake = IntakeResult(
                appointment_confirmed=intake_raw["appointment_confirmed"],
                reschedule_requested=intake_raw["reschedule_requested"],
                rescheduled_to=rescheduled_to,
                patient_reports=reports,
                consent_given=intake_raw["consent_given"],
                call_completed=intake_raw["call_completed"],
            )

        return CallResult(
            run_id=raw["run_id"],
            calle_status=raw["calle_status"],
            intake=intake,
            transcript=raw.get("transcript"),
            evidence=raw.get("evidence", []),
            call_id=raw.get("call_id"),
            duration_seconds=raw.get("duration_seconds"),
            raw_calle_response=raw.get("raw_calle_response", {}),
        )
