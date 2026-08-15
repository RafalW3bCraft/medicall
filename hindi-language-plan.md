# Hindi Language Support Plan

## Overview

MediCall already has a `language` field on every `Appointment` and passes
`--language <value>` to the CALL-E CLI when the language is not English.
CALL-E handles the actual translation of the conversation automatically.

The gap is that `goal_builder.py` only puts `Language: {language}` as a
small trailing note in the goal. For non-English languages CALL-E needs a
**prominent explicit conduct instruction** at the top of the goal, not a hint
at the bottom, so it reliably operates in the requested language throughout.

Scope: goal builder improvement, example file update, one new scenario
fixture, one new integration test.  
Nothing changes in `real_adapter.py`, the policy engine, or the API.

---

## Sub-Tasks

---

### ST-1 — Strengthen language instruction in goal_builder.py

**Intent**
When `language` is anything other than `"English"`, prepend a clear
conduct instruction to the goal so CALL-E opens the call and runs the
entire conversation in that language. The goal content (steps and rules)
stays in English — CALL-E translates the delivery.

**Expected Outcomes**
- `build_goal()` returns a goal that starts with
  `"Conduct this entire call in {language}.\n\n"` when `language != "English"`
- The trailing `Language: {language}` line is removed (it is superseded by
  the leading instruction)
- English calls are unchanged

**Todo List**
1. In `goal_builder.py`, add a `_LANGUAGE_PREFIX` constant:
   `"Conduct this entire call in {language}. Speak only in {language} throughout.\n\n"`
2. In `build_goal()`, prepend `_LANGUAGE_PREFIX.format(language=...)` to the
   returned string when `appointment.language.strip().lower() != "english"`
3. Remove the `Language: {language}` line from `_GOAL_TEMPLATE` (it is now
   covered by the leading instruction for non-English, and unnecessary for English)

**Relevant Context**
- `medicall/medicall/healthcare/goal_builder.py` — `_GOAL_TEMPLATE` and `build_goal()`
- `medicall/medicall/calle/real_adapter.py` line 167 — `--language` flag already set correctly

**Status** — `[x] done`

---

### ST-2 — Add Hindi appointment to appointments.example.json

**Intent**
Add a second entry to the example batch file using `"language": "Hindi"` so
the batch runner demo immediately exercises Hindi without any extra config.

**Expected Outcomes**
- `appointments.example.json` has two entries: English (Jane Smith) and Hindi (Jane Smith)
- Both use the same phone number `+918160094043` and region `"IN"`
- The Hindi entry has a different appointment time so calls don't collide

**Todo List**
1. In `examples/appointments.example.json`, change the second "John Doe" entry
   to a second "Jane Smith" entry with `"language": "Hindi"` and
   `"appointment_time": "11:00"` (different slot from the English one)

**Relevant Context**
- `medicall/examples/appointments.example.json`

**Status** — `[x] done`

---

### ST-3 — Add Hindi scenario fixture + integration test

**Intent**
Verify that when `language="Hindi"` flows through the engine, the goal
text contains the Hindi conduct instruction and the result parses correctly.

**Expected Outcomes**
- New `tests/scenarios/scenario_001_confirm_hindi.json` — identical to
  scenario_001_confirm but with a note in the raw CALL-E content indicating
  Hindi context (activity message says "Hindi call")
- New test `test_scenario_hindi_goal_prefix` in `test_coordinator.py`
  confirms the built goal starts with the Hindi conduct prefix when language
  is set to Hindi
- All 44 existing tests still pass; total becomes 45

**Todo List**
1. Copy `tests/scenarios/scenario_001_confirm.json` →
   `tests/scenarios/scenario_001_confirm_hindi.json`, change `run_id` to
   `"rec-run-001-hi"` and one activity message to `"Hindi call completed"`
2. In `tests/integration/test_coordinator.py`, add
   `test_scenario_hindi_goal_prefix`: create an appointment with
   `language="Hindi"`, call `build_goal(appointment)`, assert the returned
   string starts with `"Conduct this entire call in Hindi."`
3. Add `test_scenario_hindi_confirm`: run the full engine with
   `RecordedCallEAdapter(scenario="scenario_001_confirm_hindi")` and
   `language="Hindi"`, assert `record.state == COMPLETED` and
   `record.policy_decision.disposition == "ROUTINE"`

**Relevant Context**
- `medicall/tests/scenarios/scenario_001_confirm.json` — copy source
- `medicall/tests/integration/test_coordinator.py` — add tests here
- `medicall/medicall/healthcare/goal_builder.py` — `build_goal()` to import

**Status** — `[x] done`

---

## Out of Scope

- Translating the goal template itself into Hindi (CALL-E handles translation)
- Adding Hindi-specific scenario fixtures for all 8 scenarios (one confirm
  scenario is enough to prove the language path)
- Any API or model changes (`language` field already exists on `Appointment`)
- Frontend or UI work
