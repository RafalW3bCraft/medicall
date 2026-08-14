"""
RealCallEAdapter — wraps the calle-ai v0.6 Python SDK.

Authentication priority (highest → lowest):
  1. CALLE_API_KEY environment variable (explicit key, ideal for CI/Docker)
  2. CLI token cache (auto-discovered from ~/.calle-mcp/cli/*/token.json)
     — populated automatically when `calle auth login` has been run

Token cache discovery is automatic: the adapter scans the default cache
directory and picks the most recently issued valid token file. No hardcoded
path hash is required.

Only used when USE_MOCK_CALLE=false. All development and unit/integration
tests must use MockCallEAdapter to avoid burning call credits.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from medicall.core.models import CallResult, CallTask, IntakeResult, PatientReport

logger = logging.getLogger(__name__)

CALL_TIMEOUT_SECONDS = float(os.getenv("CALL_TIMEOUT_SECONDS", "300"))
POLL_INTERVAL_SECONDS = float(os.getenv("POLL_INTERVAL_SECONDS", "2"))

_DEFAULT_CACHE_ROOT = Path.home() / ".calle-mcp" / "cli"


def _resolve_api_key() -> str:
    """
    Resolve the CALL-E API key using the authentication priority chain.

    Priority:
      1. CALLE_API_KEY env var (explicit, for CI/Docker)
      2. CLI token cache — scanned from CALLE_CACHE_ROOT or ~/.calle-mcp/cli/

    Raises RuntimeError if no usable credential is found.
    """
    # Priority 1 — explicit env var
    api_key = os.getenv("CALLE_API_KEY", "").strip()
    if api_key:
        logger.debug("Using CALLE_API_KEY from environment")
        return api_key

    # Priority 2 — CLI token cache
    return _read_token_from_cache()


def _read_token_from_cache() -> str:
    """
    Auto-discover and read the access token from the CALL-E CLI token cache.

    Scans CALLE_CACHE_ROOT (default: ~/.calle-mcp/cli/) for token.json files
    and returns the access_token from the most recently issued valid one.

    Raises RuntimeError if no usable token is found.
    """
    cache_root_env = os.getenv("CALLE_CACHE_ROOT", "").strip()
    cache_root = Path(cache_root_env) if cache_root_env else _DEFAULT_CACHE_ROOT

    if not cache_root.exists():
        raise RuntimeError(
            f"CALL-E token cache directory not found: {cache_root}\n"
            "Run `calle auth login` to authenticate, or set CALLE_API_KEY."
        )

    # Scan all subdirectories for token.json files
    token_files = sorted(cache_root.glob("*/token.json"))
    if not token_files:
        raise RuntimeError(
            f"No token.json found under {cache_root}\n"
            "Run `calle auth login` to authenticate, or set CALLE_API_KEY."
        )

    # Try each token file, pick the first with a valid access_token
    errors: list[str] = []
    for token_path in token_files:
        try:
            data = json.loads(token_path.read_text())
            token_field = data.get("token")
            if not token_field:
                errors.append(f"{token_path}: missing 'token' field")
                continue
            if isinstance(token_field, dict):
                access_token = token_field.get("access_token", "").strip()
                if access_token:
                    logger.debug("Using token from cache: %s", token_path)
                    return access_token
                errors.append(f"{token_path}: 'token.access_token' is empty")
            elif isinstance(token_field, str) and token_field.strip():
                logger.debug("Using token (string) from cache: %s", token_path)
                return token_field.strip()
            else:
                errors.append(f"{token_path}: unrecognised token format")
        except (json.JSONDecodeError, OSError) as exc:
            errors.append(f"{token_path}: {exc}")

    raise RuntimeError(
        "No usable CALL-E token found in cache.\n"
        "Run `calle auth login` to authenticate, or set CALLE_API_KEY.\n"
        "Details:\n" + "\n".join(f"  {e}" for e in errors)
    )


class RealCallEAdapter:
    """
    Production CALL-E adapter using the calle-ai v0.6 Python SDK.

    Resolves credentials automatically — no hardcoded paths or keys.
    See _resolve_api_key() for the authentication priority chain.
    """

    async def execute(self, task: CallTask) -> CallResult:
        """
        Run a CALL-E call using the v0.6 SDK.

        calls.create_and_wait(task, recipient, result_schema, idempotency_key)
        → polls internally until terminal status
        → returns parsed CallResult
        """
        try:
            from calle import CalleClient  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "calle-ai is not installed. "
                "Activate the venv and run: pip install calle-ai"
            ) from exc

        api_key = _resolve_api_key()
        client = CalleClient(api_key=api_key)

        logger.info(
            "Starting CALL-E call | appointment=%s attempt=%d",
            task.appointment_id,
            task.attempt_number,
        )

        recipient = {"phone": task.phone}
        result_schema = _build_result_schema()

        logger.info(
            "Submitting to CALL-E | idempotency_key=%s",
            task.idempotency_key,
        )

        raw: dict = await asyncio.to_thread(
            client.calls.create_and_wait,
            task=task.goal,
            recipient=recipient,
            result_schema=result_schema,
            idempotency_key=task.idempotency_key,
            timeout_seconds=CALL_TIMEOUT_SECONDS,
            interval_seconds=POLL_INTERVAL_SECONDS,
        )

        logger.info(
            "CALL-E call complete | call_id=%s status=%s",
            raw.get("id"),
            raw.get("status"),
        )

        return _parse_result(raw)


# ── Result schema ──────────────────────────────────────────────────────────────

def _build_result_schema() -> dict:
    """
    Build the structured result schema passed to CALL-E.

    Maps to IntakeResult fields. CALL-E fills this from the conversation.
    No clinical fields — only patient-reported operational data.
    """
    return {
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
            "description": "New date if rescheduling requested (ISO date, e.g. 2026-09-01).",
            "nullable": True,
        },
        "rescheduled_time": {
            "type": "string",
            "description": "New time if rescheduling requested (HH:MM, e.g. 14:30).",
            "nullable": True,
        },
        "patient_reports": {
            "type": "array",
            "description": (
                "Patient-reported changes since booking. "
                "Record verbatim patient statements only. "
                "No clinical interpretation, no diagnosis, no medical advice."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "patient_statement": {
                        "type": "string",
                        "description": "Exact words used by the patient.",
                    },
                    "normalized_description": {
                        "type": "string",
                        "description": "Neutral plain-language restatement.",
                    },
                },
            },
        },
        "consent_given": {
            "type": "boolean",
            "description": "Whether the patient agreed to the information collection.",
        },
    }


# ── Result parsing ─────────────────────────────────────────────────────────────

def _parse_result(raw: dict) -> CallResult:
    """Parse a calle-ai v0.6 call response dict into a MediCall CallResult."""
    status = raw.get("status", "FAILED").upper()

    _STATUS_MAP = {
        "COMPLETED": "COMPLETED",
        "FAILED": "FAILED",
        "NO_ANSWER": "NO_ANSWER",
        "BUSY": "BUSY",
        "CANCELLED": "CANCELLED",
        "CANCELED": "CANCELED",
        "VOICEMAIL": "VOICEMAIL",
    }
    calle_status = _STATUS_MAP.get(status, status)

    result: dict = raw.get("result") or {}
    transcript: str | None = raw.get("transcript") or result.get("transcript")
    call_id: str | None = str(raw["id"]) if raw.get("id") else None

    intake = _parse_intake(result, calle_status)

    return CallResult(
        run_id=call_id or "unknown",
        calle_status=calle_status,
        intake=intake,
        transcript=transcript,
        evidence=[],
        call_id=call_id,
        raw_calle_response=raw,
    )


def _parse_intake(result: dict, calle_status: str) -> IntakeResult | None:
    """Parse the structured result dict into an IntakeResult."""
    if calle_status != "COMPLETED" or not result:
        return None
    try:
        reports = [
            PatientReport(
                patient_statement=r.get("patient_statement", ""),
                normalized_description=r.get("normalized_description", ""),
            )
            for r in (result.get("patient_reports") or [])
            if isinstance(r, dict) and r.get("patient_statement")
        ]
        return IntakeResult(
            appointment_confirmed=bool(result.get("appointment_confirmed", False)),
            reschedule_requested=bool(result.get("reschedule_requested", False)),
            rescheduled_to=None,
            patient_reports=reports,
            consent_given=bool(result.get("consent_given", True)),
            call_completed=True,
        )
    except Exception as exc:
        logger.warning("Could not parse CALL-E intake result: %s", exc)
        return None
