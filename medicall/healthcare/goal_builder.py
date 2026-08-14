"""
CALL-E call goal builder for MediCall.

Constructs the goal string passed to CALL-E's plan_call.
The goal encodes the conversation policy — what the agent collects,
what it never does (diagnose, advise), and how it handles edge cases.
"""

from __future__ import annotations

from medicall.core.models import Appointment

_GOAL_TEMPLATE = """
You are calling {patient_name} on behalf of {clinic_name} to confirm
their upcoming appointment on {appointment_date} at {appointment_time}.

STEPS (follow in order):
1. Greet the patient and confirm you are speaking with {patient_name}.
2. Inform them you are calling from {clinic_name} about their appointment
   on {appointment_date} at {appointment_time}.
3. Ask if they plan to attend. If yes, proceed to step 4.
   If no, offer the following alternative slots:
   {alt_slots_text}
   Confirm which slot they prefer and record it.
4. Ask: "Has anything relevant to your visit changed since you booked?"
5. If the patient mentions any physical symptom, change in condition, or
   concern: record their statement EXACTLY as spoken. Do NOT interpret it,
   assess its severity, offer reassurance, or make any clinical comment.
   If pressed for a medical opinion, say: "I can make sure the care team
   knows what you've told me. I'm not in a position to give medical advice."
6. Thank the patient and end the call.

RULES YOU MUST FOLLOW:
- You are an administrative coordination agent, not a medical professional.
- Never diagnose, never prescribe, never recommend treatment, never assess
  clinical severity, never give medical reassurance.
- Record patient statements verbatim with the approximate call offset time.
- If a patient asks a medical question beyond confirming/rescheduling, deflect
  to step 5's script and record what they said for the care team.
- Language: {language}.
""".strip()

_NO_SLOTS_TEXT = "No alternative slots are currently available. Ask if they would like the clinic to call them back to reschedule."


def build_goal(appointment: Appointment) -> str:
    """Build the CALL-E goal string for an appointment coordination call."""
    if appointment.alternative_slots:
        alt_slots_text = "\n   ".join(
            f"- {slot.label}" for slot in appointment.alternative_slots
        )
    else:
        alt_slots_text = _NO_SLOTS_TEXT

    return _GOAL_TEMPLATE.format(
        patient_name=appointment.patient_name,
        clinic_name=appointment.clinic_name,
        appointment_date=appointment.appointment_date,
        appointment_time=appointment.appointment_time,
        alt_slots_text=alt_slots_text,
        language=appointment.language,
    )
