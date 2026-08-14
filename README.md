# MediCall

**Pre-arrival care coordination powered by CALL-E.**

MediCall turns the routine pre-arrival phone call into an auditable coordination
workflow. CALL-E calls patients, collects patient-reported information with
consent, and produces a structured human-review handoff — before the patient
arrives.

> **MediCall doesn't replace clinical judgment. It makes the phone work around
> clinical care actionable before the patient arrives.**

---

## The Problem

Healthcare clinics often learn important patient-reported changes only when
the patient physically arrives. Staff spend hours on hold manually confirming
appointments. MediCall automates this phone work and turns every pre-arrival
call into a structured, auditable workflow.

## How It Works

```
Appointment
     ↓
CALL-E (outbound call)
     ↓
Patient conversation
     ↓
Structured result + evidence
     ↓
Deterministic policy
     ↓
Human workflow (ROUTINE / HUMAN_REVIEW / ESCALATION)
     ↓
Staff handoff card
```

**CALL-E is the execution substrate. MediCall is the workflow intelligence.**
The policy engine is deterministic — MediCall never makes a clinical decision.

---

## Quick Start

### Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (installed automatically)
- CALL-E CLI authenticated (`calle auth status`)

### Install

```bash
git clone <repo-url> medicall
cd medicall
uv pip install -e ".[dev]"
cp .env.example .env
```

### Run the demo (mock — no real calls)

```bash
bash examples/demo.sh
```

### Run the eval harness

```bash
python -m eval.run_eval
```

Expected output:
```
MediCall Eval Harness
──────────────────────────────────────────────────────
Scenario                                    Result
──────────────────────────────────────────────────────
✓  001 — Confirm                            PASS
✓  002 — Reschedule                         PASS
✓  003 — No answer (1 attempt)              PASS
✓  004 — Consent declined                   PASS
✓  005 — New symptom → HUMAN_REVIEW         PASS
✓  006 — Ambiguous response → HUMAN_REVIEW  PASS
✓  007 — Medical advice boundary            PASS
✓  008 — Escalation path                    PASS
✓  009 — Idempotency                        PASS
✓  010 — Max retries                        PASS
──────────────────────────────────────────────────────
  10 passed, 0 failed
```

### Run tests

```bash
pytest tests/ -v
```

### Start the API (mock mode)

```bash
USE_MOCK_CALLE=true uvicorn medicall.api.main:app --reload
# POST http://localhost:8000/appointments/
# GET  http://localhost:8000/appointments/{id}
# GET  http://localhost:8000/health
```

### Run a real CALL-E call

```bash
# Ensure authenticated
calle auth status

# Set USE_MOCK_CALLE=false in .env, then:
USE_MOCK_CALLE=false uvicorn medicall.api.main:app --reload
```

---

## Architecture

```
MediCall
├── Coordination Engine     ← reusable orchestration core
│   ├── WorkflowStateMachine
│   ├── CALL-E Adapter (Real | Mock)
│   ├── ResultValidator
│   ├── PolicyEngine        ← D = f(R, C, P), deterministic
│   └── HandoffGenerator
│
├── Healthcare Policy       ← domain-specific rules
│   ├── ConsentPolicy
│   ├── IntakeSchema
│   └── DispositionPolicy
│
└── FastAPI layer
```

### State Machine (15 states)

`CREATED → CALL_PENDING → CALLING → CONNECTED → CONSENT_OFFERED →
CONSENTED → INTAKE → VALIDATION → POLICY_EVALUATION →
ROUTINE | HUMAN_REVIEW | ESCALATION → COMPLETED`

With retry loop: `NO_ANSWER → RETRY_PENDING → CALL_PENDING`

### Safety Boundary (4 layers)

1. Conversation policy in CALL-E goal text
2. Pydantic schema validation (forbidden fields raise at construction)
3. Semantic boundary check (regex patterns on transcripts)
4. Deterministic policy engine (no LLM in the decision path)

---

## CALL-E Integration

MediCall uses the full `plan_call → run_call → get_call_run` lifecycle:

```python
plan = await client.plan_call(to_phones=[phone], goal=goal)
run  = await client.run_call(plan_id=plan.plan_id, confirm_token=plan.confirm_token)
# poll until terminal:
while run.status not in TERMINAL_STATUSES:
    run = await client.get_call_run(run_id=run.run_id)
```

Idempotency keys are derived from `sha256(workflow_id:appointment_id:attempt)`.

---

## Contribution

This project is submitted to the [CALL-E Hackathon](https://call-e.devpost.com)
under the **Agent Skills** contribution area as a reusable
`pre-arrival-coordination` skill.

See [SKILL.md](./SKILL.md) for the reusable pattern documentation.

---

## License

MIT
