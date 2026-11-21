"""Lead qualification questions for a clinic enquiry.

Each entry is (field_name, question). Answers are stored on the conversation
state under field_name so the summary and handoff can use them directly.
"""

LEAD_QUESTIONS = [
    ("name", "May I have your name, please?"),
    ("treatment", "Which treatment are you interested in (e.g. Botox, fillers, or a free consultation)?"),
    ("preferred_time", "What day and time would suit you for an appointment? We're open Mon–Sat, 9 am–7 pm."),
    ("contact", "What's the best phone number or WhatsApp to reach you on?"),
]

FIELD_LABELS = {
    "name": "Name",
    "treatment": "Treatment of interest",
    "preferred_time": "Preferred time",
    "contact": "Contact",
}
