"""
RealCallEAdapter — executes CALL-E calls via the `calle` CLI subprocess.

Why CLI instead of Python SDK:
  The calle-ai Python SDK (v0.6) uses api.heycall-e.com and requires an
  `iams_live_...` API key from the dashboard. The `calle` CLI uses the
  MCP OAuth path (seleven-mcp-sg.airudder.com) and authenticates via the
  token written by `calle auth login`. These are two separate auth systems.

  Using the CLI means a single `calle auth login` is all that is needed —
  no separate API key, no dashboard credential required.

Flow:
  calle call start --to-phone <E.164> --goal <text> --json
      → returns {run_id, status_result: {structuredContent: <get_call_run>}}

  If not yet terminal, poll:
  calle call status --run-id <id> --json
      → returns {result: {structuredContent: <get_call_run>}}

Console activity:
  During each poll cycle the activity list from the structuredContent is
  printed to stdout so operators running the CLI or eval harness can follow
  the call in real-time:
    [HH:MM:SS] <message>
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
from pathlib import Path

from medicall.core.models import (
    AppointmentSlot,
    CallResult,
    CallTask,
    IntakeResult,
    PatientReport,
)
from medicall.core.state_machine import CALLE_TERMINAL_STATUSES

logger = logging.getLogger(__name__)

CALL_TIMEOUT_SECONDS = float(os.getenv("CALL_TIMEOUT_SECONDS", "300"))
POLL_INTERVAL_SECONDS = float(os.getenv("POLL_INTERVAL_SECONDS", "10"))

# Attribution env required by the CALL-E skill spec
_CALLE_ENV = {
    "CALLE_SOURCE": "skills_sh",
    "CALLE_INTEGRATION": "skills_sh_skill",
    "CALLE_INTEGRATION_VERSION": "0.1.0",
}

# Directories to search for the calle binary, in priority order
_CALLE_SEARCH_PATHS = [
    # Repo-local CLI (when running inside the call-e-integrations repo)
    Path("packages/cli/bin/calle.js"),
    # npm global with user prefix
    Path.home() / ".npm-global" / "bin" / "calle",
    # npm global system
    Path("/usr/local/bin/calle"),
]


def _find_calle_binary() -> list[str]:
    """
    Locate the `calle` executable or node script.

    Returns a command prefix list, e.g.:
      ["calle"]
      ["node", "/path/to/calle.js"]

    Raises RuntimeError if calle is not found.
    """
    # 1. Check CALLE_BIN env override
    calle_bin = os.getenv("CALLE_BIN", "").strip()
    if calle_bin:
        return [calle_bin]

    # 2. Check well-known paths
    for path in _CALLE_SEARCH_PATHS:
        if path.exists():
            if path.suffix == ".js":
                return ["node", str(path)]
            return [str(path)]

    # 3. shutil.which — honours $PATH
    which = shutil.which("calle")
    if which:
        return [which]

    raise RuntimeError(
        "calle CLI not found. Install it with:\n"
        "  npm install -g @call-e/cli\n"
        "or set CALLE_BIN=/path/to/calle in your environment."
    )


def _build_env() -> dict[str, str]:
    """Build the subprocess environment with CALL-E attribution vars."""
    env = os.environ.copy()
    env.update(_CALLE_ENV)
    return env


def _print_activity(content: dict, seen_ts: set[str]) -> set[str]:
    """
    Print new activity items from a structuredContent dict to stdout.

    Returns the updated set of already-printed timestamps so callers can
    avoid printing duplicates across poll cycles.
    """
    activity = content.get("activity") or []
    for item in activity:
        ts = item.get("ts", "")
        msg = item.get("message", "")
        # Use ts+msg as dedup key — some items may share timestamps
        key = f"{ts}|{msg}"
        if key not in seen_ts:
            seen_ts.add(key)
            label = f"[{ts}]" if ts else "[----]"
            print(f"  {label} {msg}", flush=True)
    return seen_ts


class RealCallEAdapter:
    """
    Production CALL-E adapter using the `calle` CLI subprocess.

    Authentication is handled by the existing CLI token cache
    (~/.calle-mcp/cli/*/token.json) written by `calle auth login`.
    No separate API key is required.

    Activity events are printed to stdout in real-time during polling so
    operators can follow the call progress in their terminal.
    """

    async def execute(self, task: CallTask) -> CallResult:
        """
        Execute a CALL-E call via CLI subprocess.

        1. `calle call start` → run_id + initial status
        2. Poll `calle call status --run-id <id>` until terminal
        3. Parse the terminal result into a CallResult
        """
        cmd_base = _find_calle_binary()
        env = _build_env()

        logger.info(
            "Starting CALL-E call | appointment=%s attempt=%d",
            task.appointment_id,
            task.attempt_number,
        )

        # Step 1: start the call
        start_cmd = cmd_base + [
            "call", "start",
            "--to-phone", task.phone,
            "--goal", task.goal,
            "--json",
        ]
        if task.language and task.language.lower() != "english":
            start_cmd += ["--language", task.language]
        if task.region:
            start_cmd += ["--region", task.region]

        logger.info("Running: %s", " ".join(start_cmd[:5]) + " ...")
        start_raw = await _run_cli(start_cmd, env)

        # Extract run_id and initial status from start output
        # start output: {run_id, status_result: {structuredContent: <get_call_run>}}
        run_id: str | None = start_raw.get("run_id")
        status_content = (
            start_raw.get("status_result", {})
            .get("structuredContent", {})
        )
        current_status = status_content.get("status", "")

        if not run_id:
            # Some CLI versions return the run_id inside structuredContent
            run_id = status_content.get("run_id")

        if not run_id:
            raise RuntimeError(
                f"calle call start did not return a run_id. Response: {start_raw}"
            )

        logger.info("CALL-E call started | run_id=%s status=%s", run_id, current_status)
        print(f"\n▶  CALL-E call started  run_id={run_id}  status={current_status}", flush=True)

        # Print any activity already available after start
        seen_activity: set[str] = set()
        seen_activity = _print_activity(status_content, seen_activity)

        # If already terminal after start, parse immediately
        if current_status.upper() in CALLE_TERMINAL_STATUSES:
            print(f"   → Terminal immediately: {current_status}\n", flush=True)
            return _parse_status_content(run_id, status_content)

        # Step 2: poll until terminal
        elapsed = 0.0
        last_content = status_content

        while elapsed < CALL_TIMEOUT_SECONDS:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            elapsed += POLL_INTERVAL_SECONDS

            status_cmd = cmd_base + [
                "call", "status",
                "--run-id", run_id,
                "--json",
            ]
            status_raw = await _run_cli(status_cmd, env)
            last_content = status_raw.get("result", {}).get("structuredContent", {})
            current_status = last_content.get("status", "")

            # Print new activity items since last poll
            seen_activity = _print_activity(last_content, seen_activity)

            logger.debug(
                "Polling | run_id=%s status=%s elapsed=%.0fs",
                run_id, current_status, elapsed,
            )

            if current_status.upper() in CALLE_TERMINAL_STATUSES:
                break

        logger.info(
            "CALL-E call terminal | run_id=%s status=%s",
            run_id, current_status,
        )
        print(f"   → Terminal: {current_status}\n", flush=True)
        return _parse_status_content(run_id, last_content)


# ── CLI runner ─────────────────────────────────────────────────────────────────

async def _run_cli(cmd: list[str], env: dict) -> dict:
    """
    Run a calle CLI command asynchronously and return its JSON output.

    Raises RuntimeError on non-zero exit or invalid JSON.
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, stderr = await proc.communicate()

    output = stdout.decode().strip()
    if not output and stderr:
        output = stderr.decode().strip()

    try:
        result = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"calle CLI returned non-JSON output.\n"
            f"Command: {' '.join(cmd[:4])}\n"
            f"stdout: {stdout.decode()[:300]}\n"
            f"stderr: {stderr.decode()[:300]}"
        ) from exc

    # CLI signals auth failure with ok=false + code=auth_required
    if isinstance(result, dict) and result.get("ok") is False:
        code = result.get("error", {}).get("code", "")
        msg = result.get("error", {}).get("message", str(result))
        if code == "auth_required":
            raise RuntimeError(
                f"CALL-E authentication required. Run: calle auth login\n{msg}"
            )
        raise RuntimeError(f"calle CLI error ({code}): {msg}")

    return result


# ── Result parsing ─────────────────────────────────────────────────────────────

def _parse_status_content(run_id: str, content: dict) -> CallResult:
    """
    Parse a get_call_run structuredContent dict into a CallResult.

    Real CALL-E response shape (confirmed from live call):
      {
        run_id, status, message,
        result: {
          summary, post_summary, transcript, call_id,
          outcome: {
            task_completed, completion_confidence: {score, label},
            evidence: [str, ...]          ← list of strings, not dicts
          },
          extracted: {
            calling: {duration_seconds, started_at, ended_at, ...},
            patient_reports, appointment_confirmed, ...
          }
        },
        activity: [...]
      }
    """
    status = (content.get("status") or "FAILED").upper()
    result_block: dict = content.get("result") or {}

    transcript: str | None = result_block.get("transcript")
    call_id: str | None = result_block.get("call_id")

    # evidence is list[str] in real CALL-E output
    evidence: list = (result_block.get("outcome") or {}).get("evidence") or []

    # Timing from extracted.calling
    extracted: dict = result_block.get("extracted") or {}
    calling: dict = extracted.get("calling") or {}
    duration_seconds: int | None = calling.get("duration_seconds")

    started_at = None
    ended_at = None
    try:
        from datetime import datetime
        if calling.get("started_at"):
            started_at = datetime.fromisoformat(
                calling["started_at"].replace("Z", "+00:00")
            )
        if calling.get("ended_at"):
            ended_at = datetime.fromisoformat(
                calling["ended_at"].replace("Z", "+00:00")
            )
    except (ValueError, TypeError):
        pass

    intake = _parse_intake(extracted, status)

    return CallResult(
        run_id=content.get("run_id") or run_id,
        calle_status=status,
        intake=intake,
        transcript=transcript,
        evidence=evidence,
        call_id=call_id,
        duration_seconds=duration_seconds,
        started_at=started_at,
        ended_at=ended_at,
        raw_calle_response=content,
    )


def _parse_intake(extracted: dict, calle_status: str) -> IntakeResult | None:
    """Parse the extracted data dict into an IntakeResult."""
    if calle_status != "COMPLETED" or not extracted:
        return None
    try:
        reports = [
            PatientReport(
                patient_statement=r.get("patient_statement", ""),
                normalized_description=r.get("normalized_description", ""),
                call_offset_seconds=r.get("call_offset_seconds"),
            )
            for r in (extracted.get("patient_reports") or [])
            if isinstance(r, dict) and r.get("patient_statement")
        ]

        # Parse rescheduled_to if present in extracted
        rescheduled_to: AppointmentSlot | None = None
        rt = extracted.get("rescheduled_to")
        if rt and isinstance(rt, dict) and rt.get("date") and rt.get("time"):
            rescheduled_to = AppointmentSlot(
                date=rt["date"],
                time=rt["time"],
                label=rt.get("label", f"{rt['date']} {rt['time']}"),
            )

        return IntakeResult(
            appointment_confirmed=bool(extracted.get("appointment_confirmed", False)),
            reschedule_requested=bool(extracted.get("reschedule_requested", False)),
            rescheduled_to=rescheduled_to,
            patient_reports=reports,
            consent_given=bool(extracted.get("consent_given", True)),
            call_completed=True,
        )
    except Exception as exc:
        logger.warning("Could not parse CALL-E intake result: %s", exc)
        return None
