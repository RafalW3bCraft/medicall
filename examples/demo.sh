#!/usr/bin/env bash
# demo.sh — one-command MediCall demo using MockCallEAdapter
# Shows the two core workflows: confirm and new-symptom → HUMAN_REVIEW
set -e

cd "$(dirname "$0")/.."

echo ""
echo "═══════════════════════════════════════════════════"
echo "  MediCall Demo — Pre-Arrival Care Coordination"
echo "═══════════════════════════════════════════════════"
echo ""

echo "▶  Workflow 1: Patient confirms, no changes (ROUTINE)"
echo "───────────────────────────────────────────────────"
USE_MOCK_CALLE=true MOCK_SCENARIO=scenario_001_confirm \
  python3 - <<'EOF'
import asyncio
from medicall.calle.mock_adapter import MockCallEAdapter
from medicall.core.events import InMemoryEventStore
from medicall.core.models import Appointment, AppointmentSlot
from medicall.engine.coordinator import CoordinationEngine

async def run():
    appt = Appointment(
        patient_name="Jane Smith",
        patient_phone="+15551110001",
        clinic_name="City Medical Centre",
        appointment_date="2026-08-17",
        appointment_time="10:00",
        language="English",
        alternative_slots=[AppointmentSlot(date="2026-08-20", time="14:30", label="Thu 20 Aug 2:30 PM")],
    )
    store = InMemoryEventStore()
    engine = CoordinationEngine(phone_port=MockCallEAdapter("scenario_001_confirm"), event_store=store)
    record = await engine.run(appt)
    print(f"  State:       {record.state.value}")
    print(f"  Disposition: {record.policy_decision.disposition}")
    print(f"  Action:      {record.policy_decision.workflow_action}")
    print(f"  Handoff:     {record.handoff_id or 'none (routine)'}")

asyncio.run(run())
EOF

echo ""
echo "▶  Workflow 2: Patient reports new symptom → HUMAN_REVIEW"
echo "───────────────────────────────────────────────────"
python3 - <<'EOF'
import asyncio
from medicall.calle.mock_adapter import MockCallEAdapter
from medicall.core.events import InMemoryEventStore
from medicall.core.models import Appointment, AppointmentSlot
from medicall.engine.coordinator import CoordinationEngine

async def run():
    appt = Appointment(
        patient_name="John Doe",
        patient_phone="+15551110002",
        clinic_name="City Medical Centre",
        appointment_date="2026-08-17",
        appointment_time="11:00",
        language="English",
        alternative_slots=[],
    )
    store = InMemoryEventStore()
    engine = CoordinationEngine(phone_port=MockCallEAdapter("scenario_005_new_symptom"), event_store=store)
    record = await engine.run(appt)
    print(f"  State:       {record.state.value}")
    print(f"  Disposition: {record.policy_decision.disposition}")
    print(f"  Action:      {record.policy_decision.workflow_action}")
    print(f"  Handoff ID:  {record.handoff_id}")
    if record.policy_decision.evidence:
        ev = record.policy_decision.evidence[0]
        print(f"  Evidence:    [{ev.call_offset_seconds}s] \"{ev.patient_statement}\"")

asyncio.run(run())
EOF

echo ""
echo "▶  Running full eval harness (10 scenarios)..."
echo "───────────────────────────────────────────────────"
python3 -m eval.run_eval

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Demo complete. CALL-E is the execution substrate."
echo "═══════════════════════════════════════════════════"
echo ""
