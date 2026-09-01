# MediCall — Hackathon Presentation

## Real World Impact

### The Problem

Every outbound pre-arrival call a clinic makes is invisible work.
A nurse calls the patient to confirm, asks if anything has changed, and either
everything is fine (call is forgotten) or the patient mentions a new symptom
(and the nurse writes it on a sticky note, tells another nurse, or pages the
physician — all informal, all lossy).

**The core problem is not that the call happens — it's that nothing structured
comes out of it.**

- New symptoms reported verbally are not reliably captured before the patient
  arrives.
- Staff time is consumed by calls that could be automated: routine confirmations,
  reschedule requests with a confirmed new slot.
- When something does need clinical attention, the triage chain depends on
  memory rather than an auditable record.

### Who It Solves It For

Clinic staff at any outpatient facility that makes pre-arrival calls:
GP practices, specialist clinics, procedure units. The problem is
practice-universal, not niche.

### Why It's Worth Building Further

- The handoff card produced by MediCall is what goes into the pre-visit prep
  chart — the artefact the care team consults before the patient walks through
  the door.
- ROUTINE dispositions require zero staff time — the call runs, the record is
  updated, the queue stays clean.
- HUMAN_REVIEW dispositions surface only what needs human attention, with
  verbatim patient statements, evidence, and a transcript excerpt already
  attached.
- The policy engine is deterministic and auditable: `D = f(R, C, P)` —
  every disposition can be traced back to a specific rule and a specific
  patient statement.

---

## Quality of the Idea

### Why This Is Non-Obvious

The obvious CALL-E use case is "automate the call". MediCall does that — but
the real contribution is the **post-call workflow**:

1. The conversation policy embedded in the goal text is the first safety layer:
   CALL-E is told explicitly what to collect and what it must never say.
2. The structured result is validated twice before any human ever sees it:
   Pydantic schema layer (forbidden clinical field names) and semantic layer
   (regex detects clinical language that should not appear in any field).
3. The policy engine is entirely deterministic — no LLM chooses the
   disposition. The same call result always produces the same disposition.
4. The handoff card contains the evidence chain: which rule fired, which
   patient statement triggered it, and at what offset in the call.

This is not "AI that makes phone calls". This is a **care coordination
workflow with a phone call as its input channel and an auditable handoff
as its output**.

### Contribution to the Community

`SKILL.md` defines the `pre-arrival-coordination` pattern in a
domain-agnostic way. The same pattern — outbound call → structured intake →
deterministic policy → human handoff — works for:

- Field service dispatch preparation
- Delivery exception coordination
- Insurance claim information collection
- Interview scheduling confirmation

The MediCall codebase is the reference implementation. Any developer can
read `SKILL.md`, pick up the pattern, and adapt it to their domain without
having to reinvent the safety boundary or the policy engine.

---

## Technical Implementation

### How CALL-E Is Used

CALL-E is the **execution substrate**. It is imported and called at runtime
via the `calle` CLI subprocess in [`medicall/calle/real_adapter.py`](medicall/calle/real_adapter.py).

Every production call goes through:

```
calle call start --to-phone <E.164> --goal <text> --json
    → {run_id, status_result: {structuredContent}}

while not terminal:
    calle call status --run-id <id> --json
        → {result: {structuredContent}}
```

- Attribution env vars set on every subprocess call:
  `CALLE_SOURCE=skills_sh CALLE_INTEGRATION=skills_sh_skill`
- Status strings normalised at parse time (`"NO ANSWER"` → `"NO_ANSWER"`)
  — discovered from live CLI output during acceptance testing.
- Language flag passed for non-English calls:
  `--language Hindi` tested end-to-end with a full engine run.

### Verified Live Calls

Two real outbound calls were placed during development and testing:

| run_id | Status | Notes |
|--------|--------|-------|
| `QI2M34K_ul65bVDaNdOZOw` | `NO_ANSWER` | First acceptance run — discovered `"NO ANSWER"` status format; bug fixed |
| `coRqOh22iCt4JLDhzulrXQ` | `COMPLETED` | Second acceptance run — call connected, bot spoke, callee responded, transcript captured; **81s end-to-end** |

### Test Suite

| Layer | Tests | Notes |
|---|---|---|
| Unit | 15 | Policy engine (8 rules), state machine, result validator |
| Integration | 31 | CoordinationEngine × 10 scenarios, handoffs router × 8 |
| Acceptance | 2 | Real CALL-E call — `CALLE_ACCEPTANCE=1 ACCEPTANCE_PHONE=+918160094043` |
| Smoke eval | 10 | All recorded scenarios via `python -m eval.run_eval` |

**Total: 46 unit+integration, 10 eval, 2 acceptance — all pass.**

### Architecture Highlights

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

**Four safety layers** — none relying on LLM judgment:
1. Conversation policy in goal text (what CALL-E collects / never says)
2. Pydantic schema (forbidden clinical field names raise `ValidationError`)
3. Semantic boundary (regex rejects forbidden clinical language in transcripts)
4. Deterministic policy (`D` is always operational, never a diagnosis)

**Components:**
- [`real_adapter.py`](medicall/calle/real_adapter.py) — CLI subprocess, polling loop, activity printer, parser
- [`coordinator.py`](medicall/engine/coordinator.py) — 15-state workflow engine
- [`policy.py`](medicall/engine/policy.py) — 6-rule deterministic policy engine
- [`validator.py`](medicall/engine/validator.py) — transcript + intake semantic boundary
- [`goal_builder.py`](medicall/healthcare/goal_builder.py) — conversation policy embedded in CALL-E goal text
- [`handoff.py`](medicall/engine/handoff.py) — evidence-linked staff handoff generator
- [`api/`](medicall/api/) — FastAPI server with `/appointments` and `/handoffs` routers

### Complete, Coherent Experience

- **CLI batch runner**: `python -m eval.run_eval --csv examples/appointments.example.json`
  — live call progress printed to terminal
- **REST API**: `uvicorn medicall.api.main:app` — `POST /appointments/` places a real call;
  `GET /handoffs/` feeds the staff review queue; `PATCH /handoffs/{id}/acknowledge`
  closes the loop when a staff member reviews the handoff
- **Docker**: `docker-compose up` — mounts the host CLI token cache into the container
