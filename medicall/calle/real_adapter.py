"""
RealCallEAdapter — wraps the calle-ai v0.6 Python SDK.

The calle-ai v0.6 SDK uses a direct REST API:
  - CalleClient(api_key=<token>) — bearer token from the CLI cache
  - client.calls.create_and_wait(task=..., recipient=..., idempotency_key=...)
  - Returns a dict with call status, result, transcript, evidence

Token is read from the same cache the `calle` CLI uses:
  ~/.calle-mcp/cli/<hash>/token.json  →  {"token": "<bearer>", ...}

Only used when USE_MOCK_CALLE=false. All development and unit/integration
tests must use MockCallEAdapter to avoid burning call credits.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from medicall.core.models import CallResult, CallTask, IntakeResult, PatientReport
from medicall.core.state_machine import CALLE_TERMINAL_STATUSES

logger = logging.getLogger(__name__)

CALL_TIMEOUT_SECONDS = float(os.getenv("CALL_TIMEOUT_SECONDS", "300"))
POLL_INTERVAL_SECONDS = float(os.getenv("POLL_INTERVAL_SECONDS", "2"))

# Default CLI token cache root
_DEFAULT_CACHE_ROOT = Path.home() / ".calle-mcp" / "cli"
# The hash subdirectory is fixed for the default channel
_DEFAULT_CACHE_HASH = "4811f3e50259ff50339bb2feef40c0e9"


def _read_token_from_cache(
    cache_root: Path | None = None,
    cache_hash: str | None = None,
) -> str:
    """
    Read the bearer token from the CALL-E CLI token cache.

    The CLI stores the token at:
      ~/.calle-mcp/cli/<hash>/token.json  →  {"token": "...", "expires_at": "..."}

    Raises RuntimeError if the token is not found or the file does not exist.
    """
    root = cache_root or Path(os.getenv("CALLE_CACHE_ROOT", str(_DEFAULT_CACHE_ROOT)))
    hash_dir = cache_hash or os.getenv("CALLE_CACHE_HASH", _DEFAULT_CACHE_HASH)
    token_path = root / hash_dir / "token.json"

    if not token_path.exists():
        raise RuntimeError(
            f"CALL-E token cache not found at {token_path}. "
            "Run `calle auth login` to authenticate."
        )

    data = json.loads(token_path.read_text())
    token_field = data.get("token")
    if not token_field:
        raise RuntimeError(
            f"CALL-E token cache at {token_path} does not contain a 'token' field. "
            "Run `calle auth login` to re-authenticate."
        )
    # token is a nested object: {"access_token": "...", "token_type": "Bearer", ...}
    if isinstance(token_field, dict):
        access_token = token_field.get("access_token")
        if not access_token:
            raise RuntimeError(
                f"CALL-E token cache at {token_path}: 'token.access_token' is missing. "
                "Run `calle auth login` to re-authenticate."
            )
        return access_token
    # Fallback: token is a bare string
    return str(token_field)


class RealCallEAdapter:
    """
    Production CALL-E adapter using the calle-ai v0.6 Python SDK.

    Uses calls.create_and_wait() with a bearer token read directly from
    the CLI token cache. No separate API key configuration needed as long
    as `calle auth login` has been run successfully.
    """

    def __init__(
        self,
        cache_root: Path | None = None,
        cache_hash: str | None = None,
    ) -> None:
        self._cache_root = cache_root
        self._cache_hash = cache_hash

    async def execute(self, task: CallTask) -> CallResult:
        """
        Run a CALL-E call using the v0.6 SDK.

        calls.create_and_wait(task, recipient, idempotency_key)
        → polls internally until terminal status
        → returns final call dict
        """
        try:
            from calle import CalleClient  # type: ignore[import]
        except ImportError as e:
            raise RuntimeError(
                "calle-ai is not installed. Run: .venv/bin/pip install calle-ai"
            ) from e

        token = _read_token_from_cache(self._cache_root, self._cache_hash)
        client = CalleClient(api_key=token)

        logger.info(
            "Starting CALL-E call for appointment=%s attempt=%d",
            task.appointment_id,
            task.attempt_number,
        )

        # Build the recipient dict — E.164 phone number
        recipient = {"phone": task.phone}

        # Build a result schema that maps to our IntakeResult fields
        result_schema = {
            "appointment_confirmed": {
                "type": "boolean",
                "description": "Whether the patient confirmed they will attend.",
            },
            "reschedule_requested": {
                "type": "boolean",
                "description": "Whether the patient asked to reschedule.",
            },
            "rescheduled_date": {
                "type": "string",
                "description": "New date chosen if rescheduling (ISO date or null).",
                "nullable": True,
            },
            "rescheduled_time": {
                "type": "string",
                "description": "New time chosen if rescheduling (HH:MM or null).",
                "nullable": True,
            },
            "patient_reports": {
                "type": "array",
                "description": (
                    "Patient-reported changes since booking. "
                    "Record verbatim statements only — no clinical interpretation."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "patient_statement": {"type": "string"},
                        "normalized_description": {"type": "string"},
                    },
                },
            },
            "consent_given": {
                "type": "boolean",
                "description": "Whether the patient consented to information collection.",
            },
        }

        logger.info("Submitting call to CALL-E API (idempotency_key=%s)", task.idempotency_key)

        # Run synchronously in a thread to avoid blocking the event loop
        raw = await asyncio.to_thread(
            client.calls.create_and_wait,
            task=task.goal,
            recipient=recipient,
            result_schema=result_schema,
            idempotency_key=task.idempotency_key,
            timeout_seconds=CALL_TIMEOUT_SECONDS,
            interval_seconds=POLL_INTERVAL_SECONDS,
        )

        logger.info(
            "CALL-E call complete: call_id=%s status=%s",
            raw.get("id"),
            raw.get("status"),
        )

        return self._parse_result(raw)

    def _parse_result(self, raw: dict) -> CallResult:
        """Parse the calle-ai v0.6 call dict into a MediCall CallResult."""
        status = raw.get("status", "FAILED").upper()

        # Map calle-ai v0.6 statuses to CALL-E terminal status set
        # v0.6 uses: completed, failed, no_answer, busy, cancelled
        status_map = {
            "COMPLETED": "COMPLETED",
            "FAILED": "FAILED",
            "NO_ANSWER": "NO_ANSWER",
            "BUSY": "BUSY",
            "CANCELLED": "CANCELLED",
            "CANCELED": "CANCELED",
            "VOICEMAIL": "VOICEMAIL",
        }
        calle_status = status_map.get(status, status)

        # Extract result fields
        result = raw.get("result") or {}
        transcript = raw.get("transcript") or result.get("transcript")
        call_id = str(raw.get("id", "")) or None

        # Parse intake from result schema output
        intake = self._parse_intake(result, calle_status)

        return CallResult(
            run_id=call_id or "unknown",
            calle_status=calle_status,
            intake=intake,
            transcript=transcript,
            evidence=[],
            call_id=call_id,
            raw_calle_response=raw,
        )

    def _parse_intake(self, result: dict, calle_status: str) -> IntakeResult | None:
        """Parse the structured result dict into an IntakeResult."""
        if calle_status not in {"COMPLETED"}:
            return None
        if not result:
            return None

        try:
            reports_raw = result.get("patient_reports") or []
            reports = [
                PatientReport(
                    patient_statement=r.get("patient_statement", ""),
                    normalized_description=r.get("normalized_description", ""),
                )
                for r in reports_raw
                if isinstance(r, dict) and r.get("patient_statement")
            ]
            return IntakeResult(
                appointment_confirmed=bool(result.get("appointment_confirmed", False)),
                reschedule_requested=bool(result.get("reschedule_requested", False)),
                rescheduled_to=None,  # detailed slot parsing can be added later
                patient_reports=reports,
                consent_given=bool(result.get("consent_given", True)),
                call_completed=True,
            )
        except Exception as exc:
            logger.warning("Could not parse CALL-E intake result: %s", exc)
            return None
