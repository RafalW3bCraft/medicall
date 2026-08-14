"""
RealCallEAdapter — wraps the calle-ai Python SDK.

This is the production adapter. It executes the full CALL-E call lifecycle:
  plan_call → run_call → poll get_call_run → parse result

Only used when USE_MOCK_CALLE=false. All development and unit/integration
tests should use MockCallEAdapter to avoid burning call credits.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime

from medicall.core.models import CallResult, CallTask, IntakeResult, PatientReport
from medicall.core.state_machine import CALLE_TERMINAL_STATUSES

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "10"))
CALL_TIMEOUT_SECONDS = int(os.getenv("CALL_TIMEOUT_SECONDS", "300"))


class RealCallEAdapter:
    """
    Production CALL-E adapter using the calle-ai Python SDK.

    Authentication is handled by the installed `calle` CLI token cache
    (~/.calle-mcp/cli/.../token.json). No API key configuration needed.
    """

    async def execute(self, task: CallTask) -> CallResult:
        """
        Run a full CALL-E call lifecycle for the given task.

        plan_call → run_call → poll get_call_run until terminal → parse
        """
        try:
            from calle import CalleClient  # type: ignore[import]
        except ImportError as e:
            raise RuntimeError(
                "calle-ai is not installed. Run: uv pip install calle-ai"
            ) from e

        client = CalleClient()

        logger.info(
            "Starting CALL-E call for appointment=%s attempt=%d",
            task.appointment_id,
            task.attempt_number,
        )

        # 1. Plan the call
        plan = await asyncio.to_thread(
            client.plan_call,
            to_phones=[task.phone],
            goal=task.goal,
            language=task.language,
            region=task.region,
        )

        if not plan.ready_to_run:
            raise RuntimeError(
                f"CALL-E plan not ready: {plan.clarifying_questions}"
            )

        # 2. Run the call
        run = await asyncio.to_thread(
            client.run_call,
            plan_id=plan.plan_id,
            confirm_token=plan.confirm_token,
        )

        run_id = run.run_id
        logger.info("CALL-E run started: run_id=%s", run_id)

        # 3. Poll until terminal
        elapsed = 0
        while run.status not in CALLE_TERMINAL_STATUSES:
            if elapsed >= CALL_TIMEOUT_SECONDS:
                raise TimeoutError(
                    f"CALL-E call timed out after {CALL_TIMEOUT_SECONDS}s"
                )
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            elapsed += POLL_INTERVAL_SECONDS
            run = await asyncio.to_thread(client.get_call_run, run_id=run_id)
            logger.debug("Polling run_id=%s status=%s", run_id, run.status)

        logger.info(
            "CALL-E call terminal: run_id=%s status=%s",
            run_id,
            run.status,
        )

        return self._parse_result(run, task)

    def _parse_result(self, run: object, task: CallTask) -> CallResult:
        """Parse a terminal CALL-E run into a MediCall CallResult."""
        result = getattr(run, "result", {}) or {}

        # Parse intake from structured extracted data, if present
        extracted = result.get("extracted", {}) if isinstance(result, dict) else {}
        intake = self._parse_intake(extracted)

        # Parse timing
        calling = extracted.get("calling", {}) if isinstance(extracted, dict) else {}
        started_at = None
        ended_at = None
        duration_seconds = None
        if isinstance(calling, dict):
            if calling.get("started_at"):
                try:
                    started_at = datetime.fromisoformat(calling["started_at"])
                except (ValueError, TypeError):
                    pass
            if calling.get("ended_at"):
                try:
                    ended_at = datetime.fromisoformat(calling["ended_at"])
                except (ValueError, TypeError):
                    pass
            duration_seconds = calling.get("duration_seconds")

        return CallResult(
            run_id=run.run_id,  # type: ignore[attr-defined]
            calle_status=run.status,  # type: ignore[attr-defined]
            intake=intake,
            transcript=result.get("transcript") if isinstance(result, dict) else None,
            evidence=result.get("outcome", {}).get("evidence", [])
            if isinstance(result, dict)
            else [],
            call_id=result.get("call_id") if isinstance(result, dict) else None,
            duration_seconds=duration_seconds,
            started_at=started_at,
            ended_at=ended_at,
            raw_calle_response=dict(result) if isinstance(result, dict) else {},
        )

    def _parse_intake(self, extracted: dict) -> IntakeResult | None:
        """
        Parse structured intake data from CALL-E extracted fields.
        Returns None if CALL-E returned no usable structured data.
        """
        if not extracted:
            return None
        try:
            reports = [
                PatientReport(
                    patient_statement=r.get("patient_statement", ""),
                    normalized_description=r.get("normalized_description", ""),
                    call_offset_seconds=r.get("call_offset_seconds"),
                )
                for r in extracted.get("patient_reports", [])
                if r.get("patient_statement")
            ]
            return IntakeResult(
                appointment_confirmed=extracted.get("appointment_confirmed", False),
                reschedule_requested=extracted.get("reschedule_requested", False),
                rescheduled_to=None,  # parsed separately if needed
                patient_reports=reports,
                consent_given=extracted.get("consent_given", True),
                call_completed=True,
            )
        except Exception as exc:
            logger.warning("Could not parse CALL-E intake data: %s", exc)
            return None
