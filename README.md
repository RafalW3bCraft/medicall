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
CALL-E outbound call  (plan_call → run_call → poll get_call_run)
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
- `calle` CLI — `npm install -g @call-e/cli` (then `calle auth login`)
- `uv` — `curl -LsSf https://astral.sh/uv/install.sh | sh`

---

## Setup

```bash
git clone <repo-url> medicall
cd medicall

# Create virtualenv and install
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# Copy env template
cp .env.example .env
# Edit .env if needed (defaults work for mock mode)
```

---

## Commands

### 1. Run the eval harness (mock — no real calls)

Runs all 10 acceptance scenarios using `MockCallEAdapter`. Confirms the
full state machine, policy engine, and handoff logic work correctly.
**No CALL-E credits used.**

```bash
source .venv/bin/activate
python -m eval.run_eval
```

Expected output:
```
MediCall Eval Harness
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

### 2. Run the unit and integration test suite

```bash
source .venv/bin/activate
pytest tests/ -v
```

All 44 tests must pass. The 2 acceptance tests are skipped by default
(they require `CALLE_ACCEPTANCE=1` to avoid burning credits).

---

### 3. Start the API server (mock mode)

Runs the FastAPI server using `MockCallEAdapter` — no real calls placed.

```bash
source .venv/bin/activate
USE_MOCK_CALLE=true uvicorn medicall.api.main:app --reload
```

Available endpoints:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/appointments/` | Create appointment + run coordination workflow |
| `GET` | `/appointments/{id}` | Get workflow status and result |
| `GET` | `/handoffs/` | List all handoffs (staff queue) |
| `GET` | `/handoffs/?disposition=HUMAN_REVIEW` | Filter by disposition |
| `GET` | `/handoffs/?pending_only=true` | Only unacknowledged handoffs |
| `GET` | `/handoffs/{id}` | Full handoff detail with evidence chain |
| `PATCH` | `/handoffs/{id}/acknowledge` | Staff acknowledges a handoff |

**Example — create an appointment:**
```bash
curl -s -X POST http://localhost:8000/appointments/ \
  -H "Content-Type: application/json" \
  -d '{
    "patient_name": "Jane Smith",
    "patient_phone": "+<E.164-number>",
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

### 4. Start the API server (real CALL-E mode)

**Uses real CALL-E calls. Requires authentication and credits.**

```bash
# Verify auth first
calle auth status

# Start with real adapter
source .venv/bin/activate
USE_MOCK_CALLE=false uvicorn medicall.api.main:app --reload
```

Then `POST /appointments/` with a real phone number — CALL-E will place
a live outbound call.

---

### 5. Run a real acceptance test call

Places a single real CALL-E outbound call to verify the full
`calle call start → calle call status` pipeline end-to-end.
**Uses 1 CALL-E credit.**

```bash
# Ensure calle is authenticated
calle auth status

source .venv/bin/activate
CALLE_ACCEPTANCE=1 ACCEPTANCE_PHONE=+<your-E.164-number> \
  pytest tests/acceptance/test_real_adapter.py -v -s
```

The test verifies:
- `calle` binary is locatable
- `calle call start` returns a `run_id`
- Polling loop completes with a terminal status
- `CallResult` is correctly parsed (no forbidden clinical fields)

---

### 6. Change the mock scenario

To test a specific workflow path without a real call:

```bash
# Available scenarios:
# scenario_001_confirm           — patient confirms, no changes → ROUTINE
# scenario_002_reschedule        — patient reschedules → ROUTINE
# scenario_003_no_answer         — no answer → RETRY / flag
# scenario_004_consent_declined  — patient declines intake → ROUTINE
# scenario_005_new_symptom       — patient reports symptom → HUMAN_REVIEW
# scenario_006_ambiguous         — unclear response → HUMAN_REVIEW
# scenario_007_medical_advice    — patient asks medical question → boundary holds
# scenario_008_escalation        — urgent symptom → HUMAN_REVIEW + handoff

source .venv/bin/activate
USE_MOCK_CALLE=true MOCK_SCENARIO=scenario_005_new_symptom \
  uvicorn medicall.api.main:app --reload
```

---

### 7. Run via Docker (one command)

```bash
# Mock mode (default — no real calls)
docker-compose up

# Real mode
USE_MOCK_CALLE=false docker-compose up
```

---

## Architecture

```
MediCall
├── core/           WorkflowState (15 states) · Pydantic models · EventStore · Idempotency
├── calle/          PhoneExecutionPort Protocol
│   ├── real_adapter.py    → calle CLI subprocess (call start + status poll)
│   └── mock_adapter.py    → replays JSON scenarios (no credits)
├── engine/         CoordinationEngine · ResultValidator · PolicyEngine · HandoffGenerator
├── healthcare/     CALL-E goal builder (conversation policy embedded in goal text)
└── api/            FastAPI · shared store · /appointments · /handoffs
```

### CALL-E integration

```python
# goal → calle call start → run_id → poll calle call status → terminal result
# All via CLI subprocess using existing OAuth token from `calle auth login`
# No separate API key required
```

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
