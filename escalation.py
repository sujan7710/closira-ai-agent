"""Rule-based escalation detection.

Each rule maps a human-readable reason to a list of regex patterns. Patterns are
matched on word boundaries, and a match is ignored when it is negated within the
few preceding words ("I'm not angry", "no complaint"), so that calm messages are
not escalated by accident.
"""

import re

ESCALATION_RULES = {
    "Complaint or frustration": [
        r"angry", r"furious", r"upset", r"annoyed", r"frustrat\w*",
        r"complain\w*", r"terrible", r"awful", r"horrible", r"worst",
        r"bad service", r"unacceptable", r"disappointed", r"unhappy", r"not happy", r"refunds?",
    ],
    "Customer requested a human": [
        r"manager", r"(real|actual) person", r"speak to (a |an )?(human|person|someone|agent|staff)",
        r"talk to (a |an )?(human|person|someone|agent|staff)", r"human agent",
    ],
    "Legal threat": [r"lawsuit", r"lawyer", r"solicitor", r"sue (you|them|the clinic)", r"suing", r"legal action"],
    "Medical question": [
        r"pregnan\w*", r"breastfeed\w*", r"side[- ]effects?", r"allerg\w*",
        r"medication", r"medicine", r"infection", r"swelling", r"swollen",
        r"bruis\w*", r"pain(ful)?", r"symptoms?", r"reaction", r"safe",
        r"risks?", r"diabet\w*", r"blood thinners?", r"lump", r"rash",
    ],
    "Pricing negotiation": [
        r"discounts?", r"cheaper", r"negotiat\w*", r"price match", r"best price",
        r"lower (the )?price", r"too expensive", r"coupon", r"promo( code)?", r"deal",
    ],
}

NEGATIONS = {"not", "no", "never", "dont", "don't", "isnt", "isn't", "wasnt", "wasn't", "without"}
NEGATION_WINDOW = 3  # words before the trigger that are checked for a negation

_COMPILED = {
    reason: [re.compile(rf"\b{p}\b", re.IGNORECASE) for p in patterns]
    for reason, patterns in ESCALATION_RULES.items()
}


def _is_negated(text, start):
    preceding = re.findall(r"[\w']+", text[:start].lower())[-NEGATION_WINDOW:]
    return any(word in NEGATIONS for word in preceding)


def check_escalation(user_input):
    """Return (True, reason) if the message must go to a human, else (False, None)."""
    for reason, patterns in _COMPILED.items():
        for pattern in patterns:
            for match in pattern.finditer(user_input):
                if not _is_negated(user_input, match.start()):
                    return True, f"{reason} (matched '{match.group(0)}')"
    return False, None
