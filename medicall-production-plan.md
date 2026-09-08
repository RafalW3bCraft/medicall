# MediCall Production Readiness Plan

## Confirmed Design Decisions

1. **VOICEMAIL / BUSY / EXPIRED** — retry exactly like `NO_ANSWER` (up to `max_retry_attempts`). Same coordinator branch, same policy rule, same `flag_for_manual_followup` action on exhaustion.
2. **Acceptance test** — uses the complete production flow: real `Appointment`, `build_goal()`, `CoordinationEngine` + `RealCallEAdapter`, phone `+918160094043` from `examples/appointments.example.json`.

---

## Top-Level Overview

**Goal:** Bring the MediCall project to a clean, submission-ready state by removing all dead weight,
fixing every real-code issue found in the audit, adding full console call-interaction summaries,
ensuring every scenario and flow is tested with real scenarios through the production parser, and
verifying all tests pass end-to-end.

**Scope:** No architectural rewrites. Changes are surgical: remove unused things, fix live bugs,
add missing console summaries, correct real CALL-E interaction parameters, and make the acceptance
test runnable with the provided real phone number.

**Non-goals:** Adding a database backend, authentication, or rate limiting (out of scope for submission).

**Key findings from audit:**
- `pyproject.toml` declares `sqlalchemy[asyncio]` and `aiosqlite` — both unused; must be removed.
- `pyproject.toml` declares `[project.scripts] medicall = "medicall.api.main:cli"` — `cli()` function does not exist; causes install error.
- `medicall/core/models.py` uses `datetime.utcnow()` which is deprecated in Python 3.12+ — must use `datetime.now(timezone.utc)`.
- `medicall/core/events.py` uses `datetime.utcnow()` — same fix needed.
- The coordinator's `_run_workflow` retry loop condition `while record.attempt_number < appointment.max_retry_attempts` is off-by-one: on `max_retry_attempts=3`, the loop fires for attempts 1, 2, 3 but `attempt_number` starts at 0 and is incremented to 1 at the top. This is correct but the NO_ANSWER retry-continue check `if record.attempt_number < appointment.max_retry_attempts` after transition means attempt 3 will not retry because 3 is not < 3. Verified against test_scenario_010_max_retries which expects `adapter.call_count == 3` — logic is correct as-is.
- `medicall/api/routers/handoffs.py` module-level `_acknowledgements: dict` is NOT cleared between API restarts. For the store reset in tests, this is handled by `clear_store` fixture in `test_handoffs_router.py` but the dict is module-level and is NOT included in the store reset. Tests that run `acknowledge_handoff` then re-query may see stale acks. The fixture must also clear `_acknowledgements`.
- `medicall/calle/real_adapter.py` — the `--language` flag is only added when language is NOT english. This is correct. The real CALL-E CLI uses `--language` for non-English calls. No issue.
- The eval harness `eval/run_eval.py` uses `_make_test_appointment` with a fake `+15550000099` number for smoke tests. For live batch mode it uses the real number from `examples/appointments.example.json`. Both are correct patterns.
- `CALLE_CACHE_ROOT` is documented in `.env.example` but never read in `real_adapter.py`. It should be used if set.
- No console call-interaction summary is printed after a full workflow run. A structured summary showing: patient, run_id, CALL-E status, disposition, action, and handoff ID should be emitted by `CoordinationEngine` after every run.
- `medicall/engine/coordinator.py` emits `EventType.WORKFLOW_COMPLETED` with `{"state": record.state}` but `WorkflowState` is an Enum — passing it directly into a dict payload that may be serialised will fail with some serialisers. The `state` value should be `record.state.value`.
- `tests/integration/test_handoffs_router.py` — the `clear_store` fixture does NOT reset the module-level `_acknowledgements` in `handoffs.py`. This causes test isolation failures when acknowledgement tests run before filter tests.
- `tests/unit/test_result_validator.py` — all tests pass and no fix needed.
- `tests/unit/test_policy_engine.py` — all tests pass and no fix needed.
- `tests/unit/test_state_machine.py` — all tests pass and no fix needed.
- `VOICEMAIL` and `BUSY` and `EXPIRED` terminal statuses are in `CALLE_TERMINAL_STATUSES` but the coordinator does NOT handle them explicitly — they fall through the `if calle_status == "NO_ANSWER"` and `if calle_status in {"DECLINED","CANCELED","CANCELLED"}` blocks and will attempt to transition to `CONNECTED` then fail or produce incorrect intake=None. These statuses need a proper fallback path.
- `hindi-language-plan.md` — planning artifact, not needed in production submission directory.
- `presentation.md` — judging artifact, keep.
- `submission.md` — keep.
- `SKILL.md` — keep (required by hackathon).

---

## Sub-Task 1 — Remove Unused Dependencies and Fix pyproject.toml

**Status:** `[ ] pending`

**Intent:** Remove the two unused production dependencies (`sqlalchemy[asyncio]`, `aiosqlite`) and
remove the broken CLI script entry point that references a non-existent `cli()` function.

**Expected Outcomes:**
- `pyproject.toml` no longer declares `sqlalchemy[asyncio]` or `aiosqlite`.
- `[project.scripts]` section removed (or the entry point deleted).
- `uv pip install -e .` completes without installing sqlalchemy or aiosqlite.
- No code change needed elsewhere (these packages are never imported).

**Todo List:**
1. In `pyproject.toml`, remove `"sqlalchemy[asyncio]>=2.0.0"` from `dependencies`.
2. In `pyproject.toml`, remove `"aiosqlite>=0.20.0"` from `dependencies`.
3. In `pyproject.toml`, remove the `[project.scripts]` section entirely (no `cli` function exists).

**Relevant Context:**
- File: `pyproject.toml` lines 11-21, 30-31
- No Python files import `sqlalchemy` or `aiosqlite`

---

## Sub-Task 2 — Fix Deprecated `datetime.utcnow()` Usage

**Status:** `[ ] pending`

**Intent:** Replace all `datetime.utcnow()` calls with `datetime.now(timezone.utc)` as `utcnow()` is
deprecated in Python 3.12+ and removed in Python 3.13. The project requires Python 3.13+.

**Expected Outcomes:**
- No `datetime.utcnow()` calls anywhere in the production source code.
- Models continue to produce correct UTC timestamps.

**Todo List:**
1. In `medicall/core/models.py`: add `timezone` to the `datetime` import, replace all `datetime.utcnow` defaults with `lambda: datetime.now(timezone.utc)`.
2. In `medicall/core/events.py`: add `timezone` to the `datetime` import, replace `datetime.utcnow` default with `lambda: datetime.now(timezone.utc)`.

**Relevant Context:**
- `medicall/core/models.py` lines 43, 196, 213 — `datetime.utcnow` used as default_factory
- `medicall/core/events.py` line 39 — `datetime.utcnow` used in `occurred_at` field

---

## Sub-Task 3 — Fix Test Isolation: Clear `_acknowledgements` in Store Reset Fixture

**Status:** `[ ] pending`

**Intent:** The module-level `_acknowledgements` dict in `medicall/api/routers/handoffs.py` is not
cleared between tests. This causes test pollution: if `test_acknowledge_handoff` runs before
`test_pending_only_filter`, the second test sees stale acknowledgements and fails.

**Expected Outcomes:**
- All 9 handoff router tests pass in any execution order.
- The `clear_store` fixture in `tests/integration/test_handoffs_router.py` resets acknowledgements.

**Todo List:**
1. In `tests/integration/test_handoffs_router.py`, import `_acknowledgements` from `medicall.api.routers.handoffs`.
2. In the `clear_store` fixture (both before and after yield), call `_acknowledgements.clear()`.

**Relevant Context:**
- `tests/integration/test_handoffs_router.py` lines 24-33 — `clear_store` fixture
- `medicall/api/routers/handoffs.py` line 79 — module-level `_acknowledgements`

---

## Sub-Task 4 — Handle VOICEMAIL / BUSY / EXPIRED Terminal Statuses in Coordinator

**Status:** `[ ] pending`

**Intent:** When CALL-E returns `VOICEMAIL`, `BUSY`, or `EXPIRED`, the coordinator falls through to
the `CONNECTED` transition path, which is incorrect — no real call was answered. These must be
treated like `NO_ANSWER` (flag for manual follow-up without retry).

**Expected Outcomes:**
- `VOICEMAIL`, `BUSY`, `EXPIRED` statuses produce disposition `ROUTINE` with `workflow_action="flag_for_manual_followup"`.
- The coordinator does NOT attempt `CONNECTED` transitions for these statuses.
- A new scenario fixture `scenario_003b_voicemail.json` tests this path.
- The policy engine has an R05 rule that handles these statuses.

**Todo List:**
1. In `medicall/engine/coordinator.py`, extend the NO_ANSWER branch to also match `VOICEMAIL`, `BUSY`, `EXPIRED` — these should transition to `NO_ANSWER` state and apply the same retry-or-complete logic.
2. In `medicall/engine/policy.py`, update `_r06_no_answer_max_attempts` to also match `VOICEMAIL`, `BUSY`, `EXPIRED` so policy evaluation succeeds for these statuses.
3. Add `tests/scenarios/scenario_003b_voicemail.json` fixture with `status: "VOICEMAIL"` and no `result` block.
4. Add `test_scenario_voicemail` to `tests/integration/test_coordinator.py`.
5. Add the voicemail case to `EVAL_CASES` in `eval/run_eval.py`.

**Relevant Context:**
- `medicall/engine/coordinator.py` lines 129-152 — NO_ANSWER and DECLINED branch
- `medicall/core/state_machine.py` lines 44-56 — `CALLE_TERMINAL_STATUSES`
- `medicall/engine/policy.py` lines 132-140 — `_r06_no_answer_max_attempts`
- `tests/scenarios/scenario_003_no_answer.json` — reference for no-answer fixture shape

---

## Sub-Task 5 — Add Full Console Call-Interaction Summary

**Status:** `[ ] pending`

**Intent:** After every workflow run (via both the API and the eval harness), print a concise,
structured summary of the call interaction to the console so operators can trace what happened
without digging into logs.

**Expected Outcomes:**
- After each `engine.run()` completes, the console shows a summary block with:
  `── MediCall Call Summary ──────────────────────────────`
  `  Patient:     <name>  (<phone>)`
  `  run_id:      <run_id | None>`
  `  CALL-E:      <calle_status>`
  `  Attempts:    <attempt_number>`
  `  Disposition: <disposition>`
  `  Action:      <workflow_action>`
  `  Handoff:     <handoff_id | —>`
  `  Error:       <error | —>`
  `────────────────────────────────────────────────────────`
- This summary is printed from `CoordinationEngine.run()` so it appears for both API calls and eval harness runs.
- The summary does NOT duplicate the real-time activity log already printed by `RealCallEAdapter._print_activity`.

**Todo List:**
1. Add a `_print_call_summary()` private function at the bottom of `medicall/engine/coordinator.py`.
2. Call `_print_call_summary(appointment, record)` at the end of `CoordinationEngine.run()`, just before `return record`.
3. The function uses `print()` with `flush=True` (same pattern as `real_adapter.py`).

**Relevant Context:**
- `medicall/engine/coordinator.py` lines 57-83 — `run()` method
- `medicall/calle/real_adapter.py` lines 153-170 — pattern for `_print_activity` console output

---

## Sub-Task 6 — Fix `EventType.WORKFLOW_COMPLETED` Payload Serialisation

**Status:** `[ ] pending`

**Intent:** `CoordinationEngine._emit` is called with `{"state": record.state}` but `record.state`
is a `WorkflowState` Enum instance. If the event payload is ever serialised (e.g., logged as JSON
or stored in a future DB), the Enum will not serialise cleanly. Pass `.value` instead.

**Expected Outcomes:**
- `WORKFLOW_COMPLETED` event payload contains `{"state": "COMPLETED"}` (string), not `{"state": <WorkflowState.COMPLETED: 'COMPLETED'>}`.

**Todo List:**
1. In `medicall/engine/coordinator.py` line 233, change `{"state": record.state}` to `{"state": record.state.value}`.

**Relevant Context:**
- `medicall/engine/coordinator.py` line 233

---

## Sub-Task 7 — Honour `CALLE_CACHE_ROOT` in Real Adapter

**Status:** `[ ] pending`

**Intent:** `CALLE_CACHE_ROOT` is documented in `.env.example` as a way to override the CLI token
cache path, but `real_adapter.py` never reads it. The env var should be passed through to the
subprocess environment so the CLI honours it when set.

**Expected Outcomes:**
- When `CALLE_CACHE_ROOT` is set, `_build_env()` includes it in the subprocess environment.
- When not set, behaviour is identical to current (no change).

**Todo List:**
1. In `medicall/calle/real_adapter.py`, update `_build_env()`: if `os.getenv("CALLE_CACHE_ROOT")`, add `"CALLE_CACHE_ROOT": <value>` to the returned env dict.

**Relevant Context:**
- `medicall/calle/real_adapter.py` lines 146-150 — `_build_env()`
- `.env.example` line referencing `CALLE_CACHE_ROOT`

---

## Sub-Task 8 — Wire Real Acceptance Test to Provided Phone Number

**Status:** `[ ] pending`

**Intent:** The acceptance test in `tests/acceptance/test_real_adapter.py` places a real CALL-E call.
The test goal currently says "This is a test call from MediCall" — this does not exercise the full
production goal builder. Update it to use the production `build_goal()` with the real appointment
data from `examples/appointments.example.json`, and document exactly how to run it with the provided
number `+918160094043`.

Also add a full-flow acceptance test: `test_real_full_workflow` that runs the entire
`CoordinationEngine` with `RealCallEAdapter` (not just the adapter alone).

**Expected Outcomes:**
- `test_real_adapter_single_call` uses the production `build_goal()`.
- `test_real_full_workflow` runs the full engine with a real call and verifies the result is a completed `WorkflowRecord` with a known terminal `calle_status`.
- Both tests remain skipped by default and only run with `CALLE_ACCEPTANCE=1 ACCEPTANCE_PHONE=+918160094043`.
- Console output shows the full call summary for the full-flow test.

**Todo List:**
1. In `tests/acceptance/test_real_adapter.py`, import `build_goal` and `Appointment`, `AppointmentSlot`.
2. Update `test_real_adapter_single_call` task goal to use `build_goal()` with a real appointment.
3. Add `test_real_full_workflow` test that creates an Appointment matching the example JSON, instantiates `CoordinationEngine` with `RealCallEAdapter`, calls `engine.run()`, and asserts `record.state == WorkflowState.COMPLETED` and `record.call_result.calle_status in CALLE_TERMINAL_STATUSES`.
4. Update the module docstring to show `ACCEPTANCE_PHONE=+918160094043` as the example.

**Relevant Context:**
- `tests/acceptance/test_real_adapter.py` — full file
- `examples/appointments.example.json` — real appointment data
- `medicall/healthcare/goal_builder.py` — `build_goal()`

---

## Sub-Task 9 — Remove `hindi-language-plan.md` Planning Artifact

**Status:** `[ ] pending`

**Intent:** `hindi-language-plan.md` is an internal planning artifact, not a project deliverable.
Remove it to keep the root directory clean for submission.

**Expected Outcomes:**
- `hindi-language-plan.md` no longer exists in the repository root.
- No other file references it.

**Todo List:**
1. Delete `hindi-language-plan.md`.

**Relevant Context:**
- File: `hindi-language-plan.md` (root)

---

## Sub-Task 10 — Verify All Tests Pass (Full Test Suite Run)

**Status:** `[ ] pending`

**Intent:** After all code changes, run the complete test suite to confirm:
- All 46 existing tests still pass.
- New tests added in sub-tasks 4 and 8 pass.
- No ruff lint errors.

**Expected Outcomes:**
- `pytest tests/unit/ tests/integration/ -v` exits 0 with all tests passing.
- `python -m eval.run_eval` (smoke test) exits 0 with all 10 scenarios passing.
- `ruff check medicall/ tests/ eval/` exits 0 with no lint errors.
- `ruff format --check medicall/ tests/ eval/` exits 0.

**Todo List:**
1. Run `pytest tests/unit/ tests/integration/ -v` — confirm all tests pass.
2. Run `python -m eval.run_eval` — confirm smoke test passes.
3. Run `ruff check medicall/ tests/ eval/` — fix any lint errors.
4. Run `ruff format --check medicall/ tests/ eval/` — fix any formatting issues.

**Relevant Context:**
- All modified files from sub-tasks 1-9
- `pyproject.toml` ruff configuration (line-length 100, target py313)

---

## Sub-Task 11 — Update README with Correct Run Commands and Console Summary

**Status:** `[ ] pending`

**Intent:** The README is currently accurate but does not document:
1. The new console call summary output format.
2. The corrected acceptance test command with the real phone number.
3. The removed CLI entry point.

**Expected Outcomes:**
- README accurately reflects the console summary output.
- README acceptance test section uses `ACCEPTANCE_PHONE=+918160094043`.
- No mention of `medicall` CLI command (removed in sub-task 1).

**Todo List:**
1. In `README.md`, update the "Acceptance test" command example to use `ACCEPTANCE_PHONE=+918160094043`.
2. In `README.md`, add a "Console Output" section describing the call summary format.
3. Remove any mention of the `medicall` CLI script command if present.

**Relevant Context:**
- `README.md` — full file (462 lines)
