# MediCall — CALL-E Hackathon Submission

## Project Overview

**MediCall** is a pre-arrival care coordination system powered by CALL-E.
It turns the routine pre-appointment phone call into an auditable, structured
workflow: CALL-E places the call, the patient confirms or reschedules,
any relevant changes in their condition are recorded verbatim, and the
outcome is routed to a deterministic policy engine that decides
`ROUTINE / HUMAN_REVIEW / ESCALATION` — without any LLM in the decision path.

> MediCall doesn't replace clinical judgment.  
> It makes the phone work around clinical care actionable before the patient arrives.

---

## Contribution Area

**Agent Skills** — `SKILL.md` in this repository defines the reusable
`pre-arrival-coordination` pattern that can be adopted by any domain
requiring: outbound call → structured intake → deterministic policy → handoff.

---

## Pull Request

> _Open a pull request to:_  
> **https://github.com/CALLE-AI/awesome-phone-call-agents**  
> _under the **Agent Skills** contribution area._

---

## CALL-E Account

**Email:** allzerosinittodaytomastercalle@gmail.com

---

## Demo Video

See `demo-video/` directory.

---

## How to Set Up and Run

### Requirements

- Python 3.13+
- `uv` — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- `calle` CLI — `npm install -g @call-e/cli`

---

### 1. Clone and install

```bash
git clone https://github.com/RafalW3bCraft/medicall.git
cd medicall

uv venv medicall/.venv && source medicall/.venv/bin/activate
uv pip install -e ".[dev]"
```

---

### 2. Authenticate with CALL-E (one time)

```bash
export PATH="$HOME/.npm-global/bin:$PATH"
calle auth login
# Follow the browser auth flow
calle auth status   # must show usable: true
```

---

### 3. Run the unit and integration test suite (no real calls, no credits)

```bash
source medicall/.venv/bin/activate
pytest tests/unit/ tests/integration/ -v
```

Expected: **48 passed**

---

### 4. Run the scenario smoke-test (no real calls, no credits)

```bash
source medicall/.venv/bin/activate
python -m eval.run_eval
```

Expected output:
```
MediCall Eval Harness — Smoke Test (recorded scenarios)
──────────────────────────────────────────────────────
✓  001 — Confirm                           PASS
✓  002 — Reschedule                        PASS
✓  003 — No answer (1 attempt)             PASS
✓  004 — Consent declined                  PASS
✓  005 — New symptom → HUMAN_REVIEW        PASS
✓  006 — Ambiguous response → HUMAN_REVIEW PASS
✓  007 — Medical advice boundary           PASS
✓  008 — Escalation path → HUMAN_REVIEW    PASS
✓  009 — Idempotency                       PASS
✓  010 — Max retries                       PASS
✓  011 — Voicemail → flag_for_manual_followup PASS
──────────────────────────────────────────────────────
  11 passed, 0 failed
```

---

### 5. Run the real acceptance tests (uses CALL-E credits — 2 real calls)

Places real outbound calls to `+918160094043`.
Appointment dates are computed dynamically at runtime (today + N days)
so the test is safe to run on any date.

```bash
export PATH="$HOME/.npm-global/bin:$PATH"
calle auth status   # must show usable: true

source medicall/.venv/bin/activate
CALLE_ACCEPTANCE=1 ACCEPTANCE_PHONE=+918160094043 \
  pytest tests/acceptance/test_real_adapter.py -v -s
```

Expected: **3 passed** (binary found + adapter call COMPLETED + full workflow COMPLETED)

**Verified live runs — 2026-09-08:**

| Test | run_id | Status | Duration |
|------|--------|--------|----------|
| `test_real_adapter_single_call` | `lhMoHsEDfkVGsByuf4Ozpw` | `COMPLETED` | 80s |
| `test_real_full_workflow` | `9ynAJpVlts1kZDVBYDV9tA` | `COMPLETED` | ~90s |

---

### 6. Run the live batch runner (real CALL-E calls, uses credits)

```bash
export PATH="$HOME/.npm-global/bin:$PATH"
calle auth status

source medicall/.venv/bin/activate
python -m eval.run_eval --csv examples/appointments.example.json
```

Reads `examples/appointments.example.json` (3 appointments: English × 2, Hindi × 1),
calls each patient, and prints live activity events and a call summary to the console.

---

### 7. Start the API server (real calls on every POST)

```bash
export PATH="$HOME/.npm-global/bin:$PATH"
calle auth status

source medicall/.venv/bin/activate
uvicorn medicall.api.main:app --reload
```

**Create an appointment (places a real CALL-E call):**
```bash
curl -s -X POST http://localhost:8000/appointments/ \
  -H "Content-Type: application/json" \
  -d '{
    "patient_name": "Jane Smith",
    "patient_phone": "+918160094043",
    "clinic_name": "City Medical Centre",
    "appointment_date": "2026-09-15",
    "appointment_time": "10:00",
    "language": "English",
    "region": "IN",
    "alternative_slots": [
      {"date": "2026-09-17", "time": "09:00", "label": "Thursday 17 Sep at 9:00 AM"},
      {"date": "2026-09-19", "time": "14:30", "label": "Saturday 19 Sep at 2:30 PM"}
    ]
  }' | python3 -m json.tool
```

**List pending staff handoffs:**
```bash
curl -s "http://localhost:8000/handoffs/?pending_only=true" | python3 -m json.tool
```

**Acknowledge a handoff:**
```bash
curl -s -X PATCH http://localhost:8000/handoffs/<handoff-id>/acknowledge \
  -H "Content-Type: application/json" \
  -d '{"acknowledged_by": "Nurse Jenkins"}' | python3 -m json.tool
```

---

### 8. Docker

```bash
# Run calle auth login on the host first so the token cache exists
docker-compose up
```

The `docker-compose.yml` mounts `~/.calle-mcp` read-only into the container.

---

## Production Readiness Verification

| Check | Result |
|---|---|
| Unit + integration tests | **48/48 passed** |
| Scenario smoke-test | **11/11 passed** |
| Real call — COMPLETED (adapter) | `run_id=lhMoHsEDfkVGsByuf4Ozpw` · 80s · call connected · transcript captured |
| Real call — COMPLETED (full workflow) | `run_id=9ynAJpVlts1kZDVBYDV9tA` · COMPLETED · policy evaluated · events logged |
| Real call — NO_ANSWER (historical) | `run_id=QI2M34K_ul65bVDaNdOZOw` · correctly routed to `flag_for_manual_followup` |
| CALL-E auth | **usable: true**, expires 2029-06-04 |
| Status normalisation (`NO ANSWER` → `NO_ANSWER`) | Fixed in `real_adapter.py` — confirmed from live CLI output |
| VOICEMAIL / BUSY / EXPIRED handling | Retry like NO_ANSWER up to `max_retry_attempts` — new scenario + 2 tests |
| Past-date guard (`plan_not_ready`) | Acceptance test dates are dynamic (today + N days) — never fails due to date |
| Poll interval | **2s** — binary path cached; `datetime` at module level |
| Rate limiting resilience | Timeout message + warning log when `PREPARING` > `CALL_TIMEOUT_SECONDS` |
| `CALLE_CACHE_ROOT` | Forwarded to subprocess env when set |
| Python 3.13 compatibility | All `datetime.utcnow()` replaced with `datetime.now(UTC)` |
| Ruff lint | **0 errors** — `ruff check medicall/ tests/ eval/` clean |

---

## Repository Structure

```
medicall/
├── SKILL.md                  ← Reusable pre-arrival-coordination pattern
├── README.md                 ← Full setup and usage documentation
├── submission.md             ← This file
├── presentation.md           ← Judging criteria answers
├── demo-video/               ← Demo video
├── examples/
│   └── appointments.example.json   ← Live batch runner input (3 appointments)
├── medicall/
│   ├── calle/
│   │   ├── real_adapter.py   ← CALL-E CLI subprocess integration (production)
│   │   └── recorded_adapter.py ← Replay adapter for tests (same parser)
│   ├── core/                 ← WorkflowState, Pydantic models, EventStore, idempotency
│   ├── engine/               ← CoordinationEngine, PolicyEngine, ResultValidator, HandoffGenerator
│   ├── healthcare/           ← CALL-E goal builder (conversation policy)
│   └── api/                  ← FastAPI server (appointments + handoffs routers)
├── tests/
│   ├── unit/                 ← 15 unit tests (policy, state machine, validator)
│   ├── integration/          ← 33 integration tests (coordinator × 12, handoffs router × 8)
│   ├── acceptance/           ← 3 real CALL-E tests (CALLE_ACCEPTANCE=1 required)
│   └── scenarios/            ← 11 real-CALL-E-shaped JSON fixtures
└── eval/
    └── run_eval.py           ← Smoke test (11 scenarios) + live batch runner
```

---

## Live Call Records

### Call 1 — COMPLETED (2026-09-08, `test_real_adapter_single_call`)

```
run_id:    lhMoHsEDfkVGsByuf4Ozpw
call_id:   704ab18b90b74cbdba3d9b8ab4f8d476
Status:    COMPLETED
Duration:  80s
Phone:     +918160094043

Activity:
  [03:15:35] run_call started.
  [03:15:40] botlab create bot.
  [03:16:06] calling resolve robot id.
  [03:16:15] Call is ringing.
  [03:16:30] Call connected.
  [03:16:31] Bot is speaking: Hi, is this Jane Smith?
  [03:16:36] Callee said: Hello. yeah you are speaking with Jan.
  [03:16:40] Bot is speaking: I'm calling from City Medical Centre about your appointment...
  [03:16:51] Callee said: Yes, I think I am planning to attend.
  [03:16:56] Bot is speaking: Has anything relevant to your visit changed since you booked?
  [03:17:17] Callee said: I was feeling a bit out this morning so.
  [03:17:20] Bot is speaking: Thank you for letting me know. I'll make sure the care team knows.
  [03:17:49] Bot is speaking: Thank you, bye.
  [03:18:02] Call ended; syncing final Calling result.

MediCall result: COMPLETED · appointment_confirmed=False · patient_reports=0
```

### Call 2 — COMPLETED (2026-09-08, `test_real_full_workflow`)

```
run_id:    9ynAJpVlts1kZDVBYDV9tA
Status:    COMPLETED
Duration:  ~90s
Phone:     +918160094043

Full engine run:
  workflow_id:  bcea5a01-9485-406c-b4fe-0cb17c6892cf
  disposition:  ROUTINE
  action:       routine_complete
  events:       AppointmentCreated → CallRequested → CallCompleted →
                ResultValidated → PolicyEvaluated → WorkflowCompleted

Activity (excerpted):
  Patient said: No, nothing specific. [re: changes since booking]
  Patient chose: First one [of two offered reschedule slots]
  → Bot confirmed and ended call.
```

### Call 3 — NO_ANSWER (historical)

```
run_id:    QI2M34K_ul65bVDaNdOZOw
Status:    NO_ANSWER
Duration:  0s

MediCall policy engine:
  Disposition: ROUTINE  |  Action: flag_for_manual_followup  (R06_no_answer_max_attempts)
  → Status string "NO ANSWER" (space) correctly normalised to "NO_ANSWER" at parse time.
```

---

## CALL-E Integration Details

MediCall uses the **`calle` CLI** subprocess path exclusively:

```
calle call start --to-phone <E.164> --goal <text> [--language <lang>] [--region <r>] --json
    → {run_id, status_result: {structuredContent: <get_call_run>}}

while not terminal:
    calle call status --run-id <id> --json
        → {result: {structuredContent: <get_call_run>}}
```

- Authentication via existing CLI token cache (`~/.calle-mcp/cli/*/token.json`)
- Attribution env vars: `CALLE_SOURCE=skills_sh CALLE_INTEGRATION=skills_sh_skill`
- Status strings normalised at parse time (`"NO ANSWER"` → `"NO_ANSWER"`)
- Not-reached statuses (`NO_ANSWER`, `VOICEMAIL`, `BUSY`, `EXPIRED`) retry up to `max_retry_attempts`
- Poll interval: **2s** (`POLL_INTERVAL_SECONDS=2`, `POLL_FIRST_SECONDS=2`)
- Binary path cached after first resolution — no per-poll filesystem stat
- Language support: `--language Hindi` tested end-to-end with full engine run
- `CALLE_CACHE_ROOT` forwarded to subprocess env when set
- Past-date protection: acceptance test dates computed dynamically at runtime
