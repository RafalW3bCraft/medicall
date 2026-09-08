# MediCall

**Pre-arrival care coordination powered by CALL-E.**

MediCall turns the routine pre-arrival phone call into an auditable, structured
coordination workflow. CALL-E places the call, collects patient-reported
information with consent, and produces a human-review handoff — before the
patient arrives.

> **MediCall doesn't replace clinical judgment.  
> It makes the phone work around clinical care actionable before the patient arrives.**

---

## How It Works

```
Appointment record
      ↓
CALL-E outbound call   (calle call start → poll calle call status)
      ↓
Patient conversation   (consent → intake → structured result)
      ↓
Deterministic policy   (D = f(R, C, P) — no LLM in the decision path)
      ↓
ROUTINE / HUMAN_REVIEW / ESCALATION
      ↓
Staff handoff card     (evidence-linked, auditable, acknowledgeable)
```

**CALL-E is the execution substrate. MediCall is the workflow intelligence.  
The policy engine is deterministic — MediCall never makes a clinical decision.**

---

## Use Cases

| Scenario | What CALL-E does | What MediCall does |
|---|---|---|
| **Appointment confirmation** | Calls patient, asks if they plan to attend | Records confirmation, routes `ROUTINE → routine_complete` |
| **Reschedule with new slot** | Offers alternative slots, records patient choice | Routes `ROUTINE → update_appointment_slot` |
| **Reschedule, no slot chosen** | Records that patient wants to reschedule | Routes `HUMAN_REVIEW → route_to_reception_queue` |
| **New symptom reported** | Records patient statement verbatim, deflects clinical questions | Routes `HUMAN_REVIEW → route_to_nurse_queue` with evidence chain |
| **Medical advice boundary** | Responds: "I can make sure the care team knows. I'm not in a position to give medical advice." | Records statement, routes to nurse queue |
| **Consent declined** | Respects patient refusal, ends call | Routes `ROUTINE → document_consent_decline`, no intake stored |
| **No answer** | Rings and disconnects after timeout | Routes `ROUTINE → flag_for_manual_followup` after max retries |
| **Ambiguous response** | Records whatever the patient said | Routes `HUMAN_REVIEW` (any patient report triggers review) |
| **Hindi language call** | Conducts entire call in Hindi | Full goal-building, policy, and handoff in Hindi with `--language Hindi` |
| **Escalation path** | Detects urgent concern, records verbatim | Routes `ESCALATION → route_to_nurse_queue` with timestamped evidence |

---

## Policy Rules

Rules are evaluated in priority order — first match wins. `D` is always operational, never clinical.

| Rule | Trigger | Disposition | Action |
|---|---|---|---|
| **R01** | Appointment confirmed, no patient reports | `ROUTINE` | `routine_complete` |
| **R02a** | Reschedule requested + new slot confirmed | `ROUTINE` | `update_appointment_slot` |
| **R02b** | Reschedule requested, no slot chosen | `HUMAN_REVIEW` | `route_to_reception_queue` |
| **R03** | Any patient report (symptom/concern) | `HUMAN_REVIEW` | `route_to_nurse_queue` |
| **R04** | Consent declined | `ROUTINE` | `document_consent_decline` |
| **R06** | No answer after max retries | `ROUTINE` | `flag_for_manual_followup` |
| **R07** | Call failed (CALL-E `FAILED` status) | `HUMAN_REVIEW` | `route_to_nurse_queue` |

---

## Requirements

- Python 3.13+
- `calle` CLI — `npm install -g @call-e/cli` then `calle auth login`
- `uv` — `curl -LsSf https://astral.sh/uv/install.sh | sh`

---

## Setup

```bash
git clone https://github.com/RafalW3bCraft/medicall.git
cd medicall

# Create virtualenv and install all dependencies
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# Authenticate with CALL-E (one time — browser flow)
export PATH="$HOME/.npm-global/bin:$PATH"
calle auth login

# Verify authentication
calle auth status   # must show: "usable": true
```

---

## Commands

### 1. Unit + integration test suite

**48 tests — no real calls, no CALL-E credits used.**

```bash
source .venv/bin/activate
pytest tests/unit/ tests/integration/ -v
```

All 48 must pass. What is tested:

| Layer | Count | Covers |
|---|---|---|
| Unit | 15 | All 7 policy rules · state machine transitions · result validator |
| Integration | 33 | CoordinationEngine × 12 scenarios · handoffs router × 8 endpoints |

The acceptance tests in `tests/acceptance/` are skipped by default (require `CALLE_ACCEPTANCE=1`).

---

### 2. Scenario smoke-test

Runs all 11 recorded scenarios through the **production parser** (`_parse_status_content`).
Exercises state machine, policy engine, and handoff logic end-to-end.
**No CALL-E credits used.**

```bash
source .venv/bin/activate
python -m eval.run_eval
```

Each scenario prints a **Call Interaction Summary** to the console, then a pass/fail line:

```
────────────────────────────────────────────────────────
  MediCall — Call Interaction Summary
────────────────────────────────────────────────────────
  Patient:     Eval Patient  (+15550000099)
  Clinic:      Eval Clinic
  Appointment: 2026-08-17 at 10:00
  run_id:      rec-run-005
  CALL-E:      COMPLETED
  Attempts:    1
  Disposition: HUMAN_REVIEW
  Action:      route_to_nurse_queue
  Handoff:     c9f8e74e-473d-43a1-8c6f-cc4c54b2ee17
────────────────────────────────────────────────────────

✓  005 — New symptom → HUMAN_REVIEW        PASS
```

Expected final tally:
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

### 3. Real acceptance tests

Places **real CALL-E outbound calls** — verifies the complete production flow
from `calle call start` through `CoordinationEngine` to final `WorkflowRecord`.
**Uses CALL-E credits (one per test that actually calls).**

Three tests:

| Test | What it verifies |
|---|---|
| `test_calle_binary_found` | calle CLI is locatable — no call placed |
| `test_real_adapter_single_call` | Adapter + production goal builder → real call → CallResult parsed |
| `test_real_full_workflow` | CoordinationEngine + RealCallEAdapter → full workflow → WorkflowRecord |

```bash
export PATH="$HOME/.npm-global/bin:$PATH"
calle auth status   # must show usable: true

source .venv/bin/activate
CALLE_ACCEPTANCE=1 ACCEPTANCE_PHONE=+918160094043 \
  pytest tests/acceptance/test_real_adapter.py -v -s
```

Expected: **3 passed** — binary located + adapter call + full workflow complete.

Full workflow console output:
```
▶  Full workflow — calling Jane Smith at +918160094043
   Clinic: City Medical Centre  |  2026-09-01 10:00
   Language: English  |  Region: IN

▶  CALL-E call started  run_id=abc123  status=PREPARING
  [02:42:08] botlab create bot.
  [02:42:26] calling resolve robot id.
  [02:42:43] Call is ringing.
  [02:42:53] Call connected.
  [02:43:00] Call ended; syncing final Calling result.
   → Terminal: COMPLETED

────────────────────────────────────────────────────────
  MediCall — Call Interaction Summary
────────────────────────────────────────────────────────
  Patient:     Jane Smith  (+918160094043)
  Clinic:      City Medical Centre
  Appointment: 2026-09-01 at 10:00
  run_id:      abc123
  CALL-E:      COMPLETED
  Attempts:    1
  Disposition: ROUTINE
  Action:      routine_complete
  Handoff:     —
────────────────────────────────────────────────────────

   workflow_id:   wf-uuid
   calle_status:  COMPLETED
   disposition:   ROUTINE
   ✓ Full production workflow acceptance test passed
```

> **Note on rate limiting:** CALL-E enforces a per-account daily call quota.
> If calls stay in `PREPARING` indefinitely, wait until midnight UTC for the
> quota to reset. This is a CALL-E infrastructure limit, not a code issue.

---

### 4. Live batch runner — multiple appointments

Reads a JSON file of appointments and places a real CALL-E call for each one
sequentially. Live activity events stream to the console.
**Uses CALL-E credits — one per appointment.**

```bash
export PATH="$HOME/.npm-global/bin:$PATH"
calle auth status

source .venv/bin/activate
python -m eval.run_eval --csv examples/appointments.example.json
```

The example file contains 3 appointments (English × 2, Hindi × 1):

```json
[
  { "patient_name": "Jane Smith",  "language": "English", "appointment_time": "10:00" },
  { "patient_name": "John Doe",    "language": "English", "appointment_time": "11:00" },
  { "patient_name": "Jane Smith",  "language": "Hindi",   "appointment_time": "14:00" }
]
```

Console output per call:
```
[1/3] Jane Smith  +918160094043
     Clinic: City Medical Centre  Appointment: 2026-09-01 10:00
────────────────────────────────────────────────────────────
▶  CALL-E call started  run_id=abc123  status=PREPARING
  [02:42:08] botlab create bot.
  [02:42:26] calling resolve robot id.
  [02:42:43] Call is ringing.
  [02:42:53] Call connected.
  [02:43:00] Call ended; syncing final Calling result.
   → Terminal: COMPLETED

   State:       COMPLETED
   CALL-E:      COMPLETED
   Disposition: ROUTINE
   Action:      routine_complete
```

**Batch JSON format** (`examples/appointments.example.json`):

```json
{
  "patient_name":      "Jane Smith",
  "patient_phone":     "+918160094043",
  "clinic_name":       "City Medical Centre",
  "appointment_date":  "2026-09-01",
  "appointment_time":  "10:00",
  "language":          "English",
  "region":            "IN",
  "alternative_slots": [
    {"date": "2026-09-03", "time": "09:00", "label": "Wednesday 3 Sep at 9:00 AM"}
  ],
  "max_retry_attempts": 3
}
```

---

### 5. API server — place a real call via HTTP

Every `POST /appointments/` places a real CALL-E call and returns the
workflow result synchronously. Requires authentication.

```bash
export PATH="$HOME/.npm-global/bin:$PATH"
calle auth status   # must show usable: true

source .venv/bin/activate
uvicorn medicall.api.main:app --reload
```

**Available endpoints:**

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check — returns `{"status":"ok"}` |
| `POST` | `/appointments/` | Create appointment + run full workflow (places real call) |
| `GET` | `/appointments/{id}` | Get workflow status and disposition |
| `GET` | `/handoffs/` | List all staff handoffs |
| `GET` | `/handoffs/?disposition=HUMAN_REVIEW` | Filter handoffs by disposition |
| `GET` | `/handoffs/?pending_only=true` | Only unacknowledged handoffs |
| `GET` | `/handoffs/{id}` | Full handoff detail — patient reports + evidence chain + transcript excerpt |
| `PATCH` | `/handoffs/{id}/acknowledge` | Staff acknowledges a handoff |

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
    "region": "IN",
    "alternative_slots": [
      {"date": "2026-09-03", "time": "09:00", "label": "Wednesday 3 Sep at 9:00 AM"},
      {"date": "2026-09-03", "time": "14:30", "label": "Wednesday 3 Sep at 2:30 PM"}
    ]
  }' | python3 -m json.tool
```

**Hindi language appointment:**
```bash
curl -s -X POST http://localhost:8000/appointments/ \
  -H "Content-Type: application/json" \
  -d '{
    "patient_name": "Jane Smith",
    "patient_phone": "+918160094043",
    "clinic_name": "City Medical Centre",
    "appointment_date": "2026-09-01",
    "appointment_time": "14:00",
    "language": "Hindi",
    "region": "IN",
    "alternative_slots": [
      {"date": "2026-09-03", "time": "10:00", "label": "बुधवार 3 सितम्बर, सुबह 10:00 बजे"}
    ]
  }' | python3 -m json.tool
```

**List pending handoffs (staff queue):**
```bash
curl -s "http://localhost:8000/handoffs/?pending_only=true" | python3 -m json.tool
```

**Filter HUMAN_REVIEW handoffs:**
```bash
curl -s "http://localhost:8000/handoffs/?disposition=HUMAN_REVIEW" | python3 -m json.tool
```

**Get full handoff detail (evidence chain + transcript excerpt):**
```bash
curl -s "http://localhost:8000/handoffs/<handoff-id>" | python3 -m json.tool
```

**Acknowledge a handoff:**
```bash
curl -s -X PATCH http://localhost:8000/handoffs/<handoff-id>/acknowledge \
  -H "Content-Type: application/json" \
  -d '{"acknowledged_by": "Nurse Jenkins"}' | python3 -m json.tool
```

**Health check:**
```bash
curl -s http://localhost:8000/health
# → {"status":"ok","service":"medicall"}
```

---

### 6. Docker

Run the full API server in a container. The container needs access to the
CALL-E token cache written by `calle auth login` on the host.

```bash
# 1. Authenticate on the host first
calle auth login

# 2. Start the container (mounts ~/.calle-mcp read-only)
docker-compose up
```

The API is then available at `http://localhost:8000`.

---

## Environment Variables

All tunable via `.env` (copy `.env.example` to `.env`):

| Variable | Default | Description |
|---|---|---|
| `POLL_INTERVAL_SECONDS` | `2` | Delay between `calle call status` polls after first |
| `POLL_FIRST_SECONDS` | `2` | Delay before the very first status poll after `call start` |
| `CALL_TIMEOUT_SECONDS` | `300` | Hard ceiling per call before adapter gives up |
| `MAX_RETRY_ATTEMPTS` | `3` | Max no-answer / voicemail / busy retries per appointment |
| `CALLE_BIN` | *(auto)* | Override path to `calle` binary if not on `$PATH` |
| `CALLE_CACHE_ROOT` | *(auto)* | Override CLI token cache root directory (`~/.calle-mcp/cli/`) |
| `LOG_LEVEL` | `INFO` | Python logging level |

---

## Architecture

```
medicall/
├── medicall/
│   ├── calle/
│   │   ├── real_adapter.py      CALL-E CLI subprocess — call start + poll + activity print
│   │   └── recorded_adapter.py  Test replay adapter — same production parser, no network
│   ├── core/
│   │   ├── models.py            Pydantic domain models (Appointment, CallResult, Handoff …)
│   │   ├── state_machine.py     15-state WorkflowState + explicit transition table
│   │   ├── events.py            Append-only EventStore
│   │   └── idempotency.py       SHA-256 idempotency key derivation
│   ├── engine/
│   │   ├── coordinator.py       CoordinationEngine — drives all state transitions
│   │   ├── policy.py            PolicyEngine — 7 deterministic rules, D = f(R,C,P)
│   │   ├── validator.py         ResultValidator — schema + semantic boundary checks
│   │   └── handoff.py           HandoffGenerator — evidence-linked staff handoff card
│   ├── healthcare/
│   │   └── goal_builder.py      CALL-E goal text builder (conversation policy)
│   └── api/
│       ├── main.py              FastAPI app
│       ├── store.py             Shared in-memory state
│       └── routers/
│           ├── appointments.py  POST /appointments/ — places real CALL-E call
│           └── handoffs.py      GET/PATCH /handoffs/ — staff review queue
├── tests/
│   ├── unit/                    15 tests: policy rules, state machine, validator
│   ├── integration/             33 tests: coordinator × 12 scenarios, handoffs router × 8
│   ├── acceptance/              3 real CALL-E tests (CALLE_ACCEPTANCE=1 ACCEPTANCE_PHONE=+918160094043)
│   └── scenarios/               11 real-CALL-E-shaped JSON fixtures
├── eval/
│   └── run_eval.py              Smoke test + live batch runner
└── examples/
    └── appointments.example.json  3-appointment batch input (English + Hindi)
```

### CALL-E Integration

```
calle call start --to-phone <E.164> --goal <text> --region <r> --language <l> --json
    → {run_id, status_result: {structuredContent: <get_call_run>}}

while not terminal:
    calle call status --run-id <id> --json
        → {result: {structuredContent: <get_call_run>}}
```

- **Auth:** existing CLI token cache (`~/.calle-mcp/cli/*/token.json`) — no separate API key
- **Attribution:** `CALLE_SOURCE=skills_sh CALLE_INTEGRATION=skills_sh_skill` on every subprocess
- **Status normalisation:** `"NO ANSWER"` (space) → `"NO_ANSWER"` (underscore) at parse time
- **Binary cache:** `_find_calle_binary()` resolves and caches on first call — no per-poll filesystem stat
- **Poll interval:** 2s default — catches terminal status in one round-trip after the call ends
- **Language:** `--language Hindi` (or any language) passed when `language != "English"`
- **Timeout warning:** if `PREPARING` persists beyond `CALL_TIMEOUT_SECONDS`, logs a rate-limit warning
- **Not-reached statuses:** `NO_ANSWER`, `VOICEMAIL`, `BUSY`, `EXPIRED` all retry up to `max_retry_attempts`, then route `ROUTINE → flag_for_manual_followup`
- **CALLE_CACHE_ROOT:** forwarded to subprocess env if set — overrides CLI token cache directory

### Safety Boundary — 4 Layers

1. **Conversation policy** — goal text explicitly prohibits clinical language, diagnosis, prescription, and medical advice
2. **Pydantic schema** — `IntakeResult` rejects forbidden field names (`diagnosis`, `severity_assessment`, etc.) at model construction
3. **Semantic boundary** — `ResultValidator` runs 7 regex patterns against transcripts and patient reports; any match routes to `HUMAN_REVIEW`
4. **Deterministic policy** — `D = f(R, C, P)` where `D` is always an operational disposition, never a clinical conclusion

**Invariant: the agent collects. Humans decide.**

### Console Call Interaction Summary

After every `engine.run()` — whether called from the API server, the eval harness, or the
acceptance tests — a structured summary is printed to stdout:

```
────────────────────────────────────────────────────────
  MediCall — Call Interaction Summary
────────────────────────────────────────────────────────
  Patient:     Jane Smith  (+918160094043)
  Clinic:      City Medical Centre
  Appointment: 2026-09-01 at 10:00
  run_id:      coRqOh22iCt4JLDhzulrXQ
  CALL-E:      COMPLETED
  Attempts:    1
  Disposition: ROUTINE
  Action:      routine_complete
  Handoff:     —
────────────────────────────────────────────────────────
```

For `HUMAN_REVIEW` or `ESCALATION` outcomes the `Handoff` line shows the UUID of the created
handoff record — retrieve it via `GET /handoffs/{id}`.

### Testing Strategy

`RecordedCallEAdapter` loads fixtures in the **real CALL-E `structuredContent` shape** and
passes them through `_parse_status_content()` — the same parser used by `RealCallEAdapter`
in production. The integration test path is byte-for-byte identical to the live path;
only the transport layer (subprocess vs. fixture file) differs.

---

## CALL-E Hackathon Submission

- **Contribution area:** Agent Skills
- **PR target:** `github.com/CALLE-AI/awesome-phone-call-agents`
- **Skill file:** [`SKILL.md`](./SKILL.md) — reusable `pre-arrival-coordination` pattern
- **Account email:** `allzerosinittodaytomastercalle@gmail.com`

See [`submission.md`](./submission.md) for the full submission checklist and live call records.  
See [`presentation.md`](./presentation.md) for judging criteria answers.

---

## License

MIT
