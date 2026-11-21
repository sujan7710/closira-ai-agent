"""Conversation summary built from the tracked conversation state."""

from lead_qualification import FIELD_LABELS, LEAD_QUESTIONS


def _bullets(items, empty):
    return "\n".join(f"- {item}" for item in items) if items else f"- {empty}"


def recommended_action(state):
    if state.escalations:
        return "Human agent to follow up (escalated: " + "; ".join(state.escalations) + ")."
    if state.qualification_complete:
        lead = state.lead
        return (
            f"Contact {lead.get('name', 'the customer')} on {lead.get('contact', 'their contact details')} "
            f"to book {lead.get('treatment', 'a treatment')} ({lead.get('preferred_time', 'time TBC')})."
        )
    if state.qualification_started:
        return "Lead qualification incomplete; follow up to collect the missing details."
    return "No action required."


def generate_summary(state):
    user_turns = sum(1 for role, _ in state.transcript if role == "user")

    lead_lines = [
        f"{FIELD_LABELS[field]}: {state.lead.get(field, '(not provided)')}"
        for field, _ in LEAD_QUESTIONS
    ] if state.qualification_started else []

    status = (
        "Complete" if state.qualification_complete
        else "In progress" if state.qualification_started
        else "Not started"
    )

    return f"""Conversation Summary
---------------------
Customer messages: {user_turns}

Topics asked about:
{_bullets(state.topics, 'None')}

Lead qualification ({status}):
{_bullets(lead_lines, 'No lead details collected')}

SOP gaps (questions the SOP could not answer):
{_bullets(state.unanswered, 'None')}

Escalations:
{_bullets(state.escalations, 'None')}

Recommended next action:
- {recommended_action(state)}"""
