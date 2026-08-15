"""
RecordedCallEAdapter — replays real-CALL-E-shaped scenario fixtures for testing.

Each fixture in tests/scenarios/*.json is a structuredContent dict (the real
get_call_run shape confirmed from a live call). This adapter loads the fixture
and passes it directly through _parse_status_content() — the same parser used
by RealCallEAdapter — ensuring the test path is identical to production.

Usage:
    adapter = RecordedCallEAdapter(scenario="scenario_005_new_symptom")
    result = await adapter.execute(task)
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from medicall.calle.real_adapter import _parse_status_content
from medicall.core.models import CallResult, CallTask

logger = logging.getLogger(__name__)

SCENARIOS_DIR = Path(__file__).parent.parent.parent / "tests" / "scenarios"


class RecordedCallEAdapter:
    """
    Test adapter that replays real-CALL-E-shaped fixtures through the
    production parser (_parse_status_content), so integration tests exercise
    the exact same parsing logic as live calls.

    Scenarios are stored in tests/scenarios/*.json as get_call_run
    structuredContent dicts (real CALL-E shape, not mock flat shape).
    """

    def __init__(
        self,
        scenario: str = "scenario_001_confirm",
        simulate_latency_seconds: float = 0.0,
    ) -> None:
        self.scenario = scenario
        self.simulate_latency_seconds = simulate_latency_seconds
        self._call_count: int = 0

    @property
    def call_count(self) -> int:
        """Number of times execute() has been called. Used in idempotency tests."""
        return self._call_count

    async def execute(self, task: CallTask) -> CallResult:
        """Load the fixture and parse it via _parse_status_content()."""
        self._call_count += 1
        if self.simulate_latency_seconds:
            await asyncio.sleep(self.simulate_latency_seconds)

        scenario_path = SCENARIOS_DIR / f"{self.scenario}.json"
        if not scenario_path.exists():
            raise FileNotFoundError(
                f"Scenario fixture not found: {scenario_path}. "
                f"Available: {[p.stem for p in SCENARIOS_DIR.glob('*.json')]}"
            )

        # Fixture is the raw structuredContent dict (real CALL-E get_call_run shape)
        content: dict = json.loads(scenario_path.read_text())

        # run_id may live at top level in fixture or inside content
        run_id: str = content.get("run_id") or f"rec-{self.scenario}"

        logger.debug(
            "RecordedCallEAdapter replaying scenario=%s for appointment=%s",
            self.scenario,
            task.appointment_id,
        )

        # Route through the production parser — same code path as RealCallEAdapter
        return _parse_status_content(run_id, content)
