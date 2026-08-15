---
name: pre-arrival-coordination
description: >
  Reusable CALL-E phone-work coordination pattern. Implements the full
  lifecycle: consent → goal-driven outbound call → structured result →
  deterministic policy → human handoff. Demonstrated through MediCall
  as a pre-arrival care coordination system for healthcare clinics.
  Generalises to any domain requiring: outbound call → structured
  information → operational workflow action.
version: "0.1.0"
---

# pre-arrival-coordination

A reusable CALL-E orchestration pattern for any domain that needs to turn
an outbound phone call into an actionable, auditable workflow.

## The Pattern

```
goal
  → consent
  → goal-driven CALL-E call
  → structured result
  → schema validation
  → deterministic policy
  → human handoff
```

CALL-E is the **execution substrate** — this skill provides the
**workflow intelligence** on top of it.

## Reference Implementation: MediCall

MediCall applies this pattern to healthcare pre-arrival coordination:

- Calls patients before their appointment
- Collects patient-reported changes (with consent)
- Produces a structured handoff for clinic staff
- Never makes a clinical decision — only operational routing

See the [`medicall/`](.) directory for the full reference implementation.

## Reusable Domains

| Domain         | Use case                                  |
|----------------|-------------------------------------------|
| Healthcare     | Pre-arrival care coordination (MediCall)  |
| Field service  | Technician dispatch preparation           |
| Logistics      | Delivery exception coordination           |
| Insurance      | Claim information collection              |
| HR             | Interview scheduling confirmation         |

## Safety Boundary

This skill enforces four safety layers:

1. **Conversation policy** — CALL-E goal text defines what the agent
   collects and explicitly prohibits clinical/diagnostic language.
2. **Schema validation** — Pydantic models reject forbidden field names
   (diagnosis, prescription, treatment_recommendation, etc.).
3. **Semantic boundary** — Regex patterns detect forbidden clinical
   language in transcripts and patient reports.
4. **Deterministic policy** — D = f(R, C, P) where D is always an
   operational disposition, never a clinical conclusion.

**Invariant:** The agent collects. Humans decide.

## Using with CALL-E

This skill uses the CALL-E `plan_call` → `run_call` → `get_call_run`
lifecycle to place real outbound calls. Authentication is handled by
the installed `calle` CLI.

```bash
# Verify CALL-E setup
calle auth status
calle mcp tools
```

## References

- `references/result-schema.md` — structured result format
- `references/workflow-pattern.md` — state machine and event flow
- `references/safety-boundary.md` — four-layer safety architecture

## Repository

https://github.com/CALLE-AI/awesome-phone-call-agents
