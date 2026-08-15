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
Appointment
     ↓
CALL-E outbound call  (calle call start → poll calle call status)
     ↓
Patient conversation  (consent → intake → structured result)
     ↓
Deterministic policy  (D = f(R, C, P) — no LLM in the decision path)
     ↓
ROUTINE / HUMAN_REVIEW / ESCALATION
     ↓
Staff handoff card    (evidence-linked, auditable)
```

**CALL-E is the execution substrate. MediCall is the workflow intelligence.  
The policy engine is deterministic — MediCall never makes a clinical decision.**

---

## Requirements

- Python 3.13+
- `calle` CLI — `npm install -g @call-e/cli` then `calle auth login`
- `uv` — `curl -LsSf https://astral.sh/uv/install.sh | sh`

---

## Setup

```bash
git clone <repo-url>
cd medicall

# Create virtualenv and install
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# Authenticate with CALL-E (one time)
export PATH="$HOME/.npm-global/bin:$PATH"
calle auth login
```

---

## Commands

### 1. Run the test suite

44 unit + integration tests — no real calls, no credits used.

```bash
source .venv/bin/activate
pytest tests/unit/ tests/integration/ -v
```

All 44 tests must pass. The acceptance tests in `tests/acceptance/` are
skipped by default (require `CALLE_ACCEPTANCE=1`).

---

### 2. Run the eval smoke-test

Runs all 10 recorded scenarios through the production parser. Confirms
the full state machine, policy engine, and handoff logic work correctly.
**No CALL-E credits used.**

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

### 3. Live batch runner (real CALL-E calls)

Places real outbound calls for each appointment in a JSON file.
Live activity events are printed to the console during each call.
**Uses CALL-E credits — ensure you are authenticated first.**

```bash
# Verify auth
export PATH="$HOME/.npm-global/bin:$PATH"
calle auth status

source .venv/bin/activate
python -m eval.run_eval --csv examples/appointments.example.json
```

The JSON file is a list of appointment objects. See
`examples/appointments.example.json` for the format.

Console output during a call:
```
[1/2] Jane Smith  +918160094043
     Clinic: City Medical Centre  Appointment: 2026-09-01 10:00
────────────────────────────────────────────────────────────
▶  CALL-E call started  run_id=abc123  status=IN_PROGRESS
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

### 4. Run a single acceptance test call

Places one real CALL-E call to verify the full `calle call start →
calle call status` pipeline end-to-end. **Uses 1 CALL-E credit.**

```bash
export PATH="$HOME/.npm-global/bin:$PATH"
calle auth status

source .venv/bin/activate
CALLE_ACCEPTANCE=1 ACCEPTANCE_PHONE=+<your-E.164-number> \
  pytest tests/acceptance/test_real_adapter.py -v -s
```

---

### 5. Start the API server

Runs the FastAPI server. Every `POST /appointments/` places a real
CALL-E call. Requires authentication.

```bash
export PATH="$HOME/.npm-global/bin:$PATH"
calle auth status

source .venv/bin/activate
uvicorn medicall.api.main:app --reload
```

Available endpoints:

| Method  | Path                             | Description                             |
|---------|----------------------------------|-----------------------------------------|
| `GET`   | `/health`                        | Health check                            |
| `POST`  | `/appointments/`                 | Create appointment + run workflow       |
| `GET`   | `/appointments/{id}`             | Get workflow status                     |
| `GET`   | `/handoffs/`                     | List all handoffs (staff queue)         |
| `GET`   | `/handoffs/?disposition=HUMAN_REVIEW` | Filter by disposition              |
| `GET`   | `/handoffs/?pending_only=true`   | Only unacknowledged handoffs            |
| `GET`   | `/handoffs/{id}`                 | Full handoff detail with evidence chain |
| `PATCH` | `/handoffs/{id}/acknowledge`     | Staff acknowledges a handoff            |

**Example — create an appointment (places a real call):**
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

**Example — list pending handoffs:**
```bash
curl -s "http://localhost:8000/handoffs/?pending_only=true" | python3 -m json.tool
```

**Example — acknowledge a handoff:**
```bash
curl -s -X PATCH http://localhost:8000/handoffs/<handoff-id>/acknowledge \
  -H "Content-Type: application/json" \
  -d '{"acknowledged_by": "Nurse Jenkins"}' | python3 -m json.tool
```

---

### 6. Docker

```bash
# Mount CALL-E token cache so the container can authenticate
docker-compose up
```

The `docker-compose.yml` mounts `~/.calle-mcp` read-only into the
container. Run `calle auth login` on the host first.

---

## Architecture

```
medicall/
├── core/           WorkflowState (15 states) · Pydantic models · EventStore · Idempotency
├── calle/
│   ├── real_adapter.py      → calle CLI subprocess (call start + status poll + activity print)
│   └── recorded_adapter.py  → replays real-shaped fixtures through production parser (tests)
├── engine/         CoordinationEngine · ResultValidator · PolicyEngine · HandoffGenerator
├── healthcare/     CALL-E goal builder (conversation policy embedded in goal text)
└── api/            FastAPI · shared store · /appointments · /handoffs
```

### CALL-E integration

```
calle call start --to-phone <E.164> --goal <text> --json
    → {run_id, status_result: {structuredContent: <get_call_run>}}

calle call status --run-id <id> --json
    → {result: {structuredContent: <get_call_run>}}
```

Authentication: existing CLI token cache (`~/.calle-mcp/cli/*/token.json`)
written by `calle auth login`. No separate API key required.

### Testing approach

Integration tests use `RecordedCallEAdapter`, which loads fixtures in the
**real CALL-E `structuredContent` shape** and passes them through the same
`_parse_status_content()` parser used in production. The test path is
identical to the live path — only the transport layer differs.

### Safety boundary (4 layers)

1. **Conversation policy** — goal text prohibits clinical language
2. **Pydantic schema** — forbidden field names raise `ValidationError` at construction
3. **Semantic boundary** — regex rejects clinical language in transcripts
4. **Deterministic policy** — `D = f(R, C, P)`, D is operational only, never a diagnosis

---

## CALL-E Hackathon Submission

- **Contribution area:** Agent Skills
- **PR target:** `github.com/CALLE-AI/awesome-phone-call-agents`
- **Skill:** `SKILL.md` — reusable `pre-arrival-coordination` pattern

See [`SKILL.md`](./SKILL.md) for the generalised pattern documentation.

---

## License

MIT
