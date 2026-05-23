def generate_summary(conversation_history, lead_answers):

    summary = f"""
Conversation Summary
---------------------

Customer Intent:
Customer asked about clinic services and pricing.

Lead Qualification Details:
"""

    for i, answer in enumerate(lead_answers, start=1):
        summary += f"\nQ{i}: {answer}"

    summary += """

SOP Gaps Identified:
- Any out-of-scope questions were escalated.

Recommended Next Action:
- Human agent follow-up if escalation occurred.
- Continue customer onboarding process.
"""

    return summary