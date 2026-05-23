ESCALATION_KEYWORDS = [
    "angry",
    "complaint",
    "refund",
    "manager",
    "human",
    "terrible",
    "bad service",
    "lawsuit"
]

def check_escalation(user_input):

    text = user_input.lower()

    for word in ESCALATION_KEYWORDS:
        if word in text:
            return True, f"Escalation triggered: {word}"

    return False, None