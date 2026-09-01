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

## How to Set Up and Run

### Requirements

- Python 3.13+
- `uv` — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- `calle` CLI — `npm install -g @call-e/cli`

---

### 1. Clone and install

```bash
git clone <repo-url>
cd medicall

uv venv && source .venv/bin/activate
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
source .venv/bin/activate
pytest tests/unit/ tests/integration/ -v
```

Expected: **46 passed**

---

### 4. Run the scenario smoke-test (no real calls, no credits)

```bash
source .venv/bin/activate
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
──────────────────────────────────────────────────────
  10 passed, 0 failed
```

---

### 5. Run a real acceptance test (uses 1 CALL-E credit)

Places a real outbound call to the number in the env var.
Verified working against `+918160094043` — live call completed in 81 seconds,
`run_id=coRqOh22iCt4JLDhzulrXQ`, `calle_status=COMPLETED`.

```bash
export PATH="$HOME/.npm-global/bin:$PATH"
calle auth status   # must show usable: true

source .venv/bin/activate
CALLE_ACCEPTANCE=1 ACCEPTANCE_PHONE=+918160094043 \
  pytest tests/acceptance/test_real_adapter.py -v -s
```

Expected: **2 passed** (binary found + real call COMPLETED)

---

### 6. Run the live batch runner (real CALL-E calls, uses credits)

```bash
export PATH="$HOME/.npm-global/bin:$PATH"
calle auth status

source .venv/bin/activate
python -m eval.run_eval --csv examples/appointments.example.json
```

Reads `examples/appointments.example.json`, calls each patient, and prints
live activity events to the console:

```
[1/3] Jane Smith  +918160094043
     Clinic: City Medical Centre  Appointment: 2026-09-01 10:00
────────────────────────────────────────────────────────────
▶  CALL-E call started  run_id=abc123  status=PREPARING
  [00:00:03] Call connected
  [00:00:35] Patient confirmed appointment
  [00:00:42] Call completed
   → Terminal: COMPLETED

   State:       COMPLETED
   CALL-E:      COMPLETED
   Disposition: ROUTINE
   Action:      routine_complete
```

---

### 7. Start the API server (real calls on every POST)

```bash
export PATH="$HOME/.npm-global/bin:$PATH"
calle auth status

source .venv/bin/activate
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
    "appointment_date": "2026-09-01",
    "appointment_time": "10:00",
    "language": "English",
    "region": "IN"
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
| Unit + integration tests | **46/46 passed** |
| Scenario smoke-test | **10/10 passed** |
| Real call — COMPLETED | `run_id=coRqOh22iCt4JLDhzulrXQ` · 7s · transcript captured · task_completed=True · confidence=0.92 high |
| Real call — NO_ANSWER | `run_id=QI2M34K_ul65bVDaNdOZOw` · correctly parsed, policy routed to `flag_for_manual_followup` |
| CALL-E auth | **usable: true**, expires 2029-05-10 |
| Status normalisation (`NO ANSWER` → `NO_ANSWER`) | **Fixed** in `real_adapter.py` — confirmed from live CLI output |
| Poll interval | **2s** (reduced from 10s) — binary path cached; `datetime` at module level |
| Rate limiting resilience | Timeout message + warning log when CALL-E provisioning stalls (`PREPARING` > 300s) |

---

## Repository Structure

```
medicall/
├── SKILL.md                  ← Reusable pre-arrival-coordination pattern
├── README.md                 ← Full setup and usage documentation
├── submission.md             ← This file
├── presentation.md           ← Judging criteria answers
├── examples/
│   └── appointments.example.json   ← Live batch runner input format
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
│   ├── integration/          ← 31 integration tests (coordinator, handoffs router)
│   ├── acceptance/           ← Real CALL-E call test (CALLE_ACCEPTANCE=1 required)
│   └── scenarios/            ← 10 real-CALL-E-shaped JSON fixtures
└── eval/
    └── run_eval.py           ← Smoke test + live batch runner
```

---

## Live Call Record

### Call 1 — COMPLETED (`run_id=coRqOh22iCt4JLDhzulrXQ`)

```
Status:       COMPLETED
Call ID:      0a042794a6ab408ca84d036307670fc6
Duration:     7s
Started:      2026-09-01 02:42:52 UTC-4
Ended:        2026-09-01 02:42:59 UTC-4

Post Summary:
  The test call connected, the required MediCall test phrase was delivered,
  and the call ended successfully.

Outcome:
  task_completed: True  |  confidence: 0.92 (high)
  evidence:
    - The callee answered the call.
    - The bot delivered the required MediCall test message.
    - The call ended after the delivery goal was completed.

Transcript:
  [00:00:00] BOT:  This is a test call from MediCall,
  [00:00:00] USER: Hello.
  [00:00:01] BOT:  a CALL-E hackathon project. test confirmed

Activity timeline:
  [02:42:04] run_call started.
  [02:42:08] botlab create bot.
  [02:42:26] calling resolve robot id.
  [02:42:28] calling create task.
  [02:42:30] calling task created.
  [02:42:30] calling task status=pending
  [02:42:35] calling task status=calling
  [02:42:43] Call is ringing.
  [02:42:53] Call connected.
  [02:42:55] Bot is speaking: This is a test call from MediCall,
  [02:42:55] Callee said: hello / Hello.
  [02:42:56] Bot is speaking: a CALL-E hackathon project. test confirmed
  [02:43:00] Call ended; syncing final Calling result.
  [02:43:09] Call ended from realtime events.
  [02:43:41] calling task status=finished
```

### Call 2 — NO_ANSWER (`run_id=QI2M34K_ul65bVDaNdOZOw`)

```
Status:       NO_ANSWER
Call ID:      60d97d0e4edc4bf4909effddd3664e8b
Duration:     0s

Post Summary:
  The test call did not connect and the recipient may be unavailable.

Outcome:
  task_completed: False
  evidence:
    - The call ended with a no-answer status.
    - No transcript or speech was captured.
    - The call duration was 0 seconds.

MediCall policy engine:
  Disposition: ROUTINE  |  Action: flag_for_manual_followup  (R06_no_answer_max_attempts)

Activity timeline:
  [02:30:57] run_call started.
  [02:31:01] botlab create bot.
  [02:31:21] calling resolve robot id.
  [02:31:30] calling task status=calling
  [02:31:40] Call is ringing.
  [02:32:03] Call ended; syncing final Calling result.
  [02:32:11] calling task status=NO ANSWER
  [02:32:32] calling task completed with status=NO ANSWER
```

---

## CALL-E Integration Details

MediCall uses the **`calle` CLI** subprocess path exclusively:

```
calle call start --to-phone <E.164> --goal <text> --json
    → {run_id, status_result: {structuredContent: <get_call_run>}}

calle call status --run-id <id> --json
    → {result: {structuredContent: <get_call_run>}}
```

- Authentication via existing CLI token cache (`~/.calle-mcp/cli/*/token.json`)
- Attribution env vars: `CALLE_SOURCE=skills_sh CALLE_INTEGRATION=skills_sh_skill`
- Status strings normalised at parse time (`"NO ANSWER"` → `"NO_ANSWER"`)
- Poll interval: **2s** (`POLL_INTERVAL_SECONDS=2`, `POLL_FIRST_SECONDS=2`)
- Binary path cached after first resolution — no per-poll filesystem stat
- Retry logic: configurable `max_retry_attempts` per appointment
- Language support: `--language Hindi` tested end-to-end with full engine run
- Rate limiting: timeout message + warning log when `PREPARING` exceeds `CALL_TIMEOUT_SECONDS`
