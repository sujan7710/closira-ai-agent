"""Rule-based escalation detection.

BASE_RULES is a library of escalation categories. Each business enables the ones
it needs, can add extra patterns per category, and can define custom categories
(e.g. "insurance" for a dental practice) in its YAML config.

Patterns are matched on word boundaries, and a match is ignored when it is negated
within the few preceding words ("I'm not angry", "no complaint").

The rules serve two purposes:
  * guardrail categories (per business, e.g. medical and legal) are always enforced,
    even when the LLM classifier disagrees: missing one is far costlier than a false alarm.
  * all enabled rules form the deterministic fallback router when the LLM classifier
    is unavailable or not confident.
"""

import re

BASE_RULES = {
    "complaint": ("Complaint or frustration", [
        r"angry", r"furious", r"upset", r"annoyed", r"frustrat\w*",
        r"complain\w*", r"terrible", r"awful", r"horrible", r"worst",
        r"bad service", r"unacceptable", r"disappointed", r"unhappy", r"not happy", r"refunds?",
    ]),
    "human_request": ("Customer requested a human", [
        r"manager", r"(real|actual) person", r"speak to (a |an )?(human|person|someone|agent|staff)",
        r"talk to (a |an )?(human|person|someone|agent|staff)", r"human agent",
    ]),
    "legal": ("Legal threat", [
        r"lawsuit", r"lawyer", r"solicitor", r"sue (you|them|the clinic)", r"suing", r"legal action",
    ]),
    "medical": ("Medical question", [
        r"pregnan\w*", r"breastfeed\w*", r"side[- ]effects?", r"allerg\w*",
        r"medication", r"medicine", r"infection", r"swelling", r"swollen",
        r"bruis\w*", r"pain(ful)?", r"symptoms?", r"reaction", r"safe",
        r"risks?", r"diabet\w*", r"blood thinners?", r"lump", r"rash",
    ]),
    "price_negotiation": ("Pricing negotiation", [
        r"discounts?", r"cheaper", r"negotiat\w*", r"price match", r"best price",
        r"lower (the )?price", r"too expensive", r"coupon", r"promo( code)?", r"deal",
    ]),
}

# Labels for escalations that do not come from keyword rules.
SYSTEM_LABELS = {
    "unanswered_limit": "More than 2 unanswered questions",
    "error": "Assistant error (LLM unavailable)",
}

NEGATIONS = {"not", "no", "never", "dont", "don't", "isnt", "isn't", "wasnt", "wasn't", "without"}
NEGATION_WINDOW = 3  # words before the trigger that are checked for a negation


def compile_patterns(patterns):
    return [re.compile(rf"\b{p}\b", re.IGNORECASE) for p in patterns]


def build_rules(enabled=None, extra_patterns=None, custom=None):
    """Return {code: (label, [compiled patterns])} for one business."""
    enabled = list(BASE_RULES) if enabled is None else enabled
    extra_patterns = extra_patterns or {}
    rules = {}
    for code in enabled:
        label, patterns = BASE_RULES[code]
        rules[code] = (label, compile_patterns(patterns + extra_patterns.get(code, [])))
    for code, spec in (custom or {}).items():
        rules[code] = (spec["label"], compile_patterns(spec["patterns"] + extra_patterns.get(code, [])))
    return rules


DEFAULT_RULES = build_rules()


def label_for(category, rules=None):
    rules = DEFAULT_RULES if rules is None else rules
    if category in rules:
        return rules[category][0]
    if category in BASE_RULES:
        return BASE_RULES[category][0]
    return SYSTEM_LABELS.get(category, category)


def _is_negated(text, start):
    preceding = re.findall(r"[\w']+", text[:start].lower())[-NEGATION_WINDOW:]
    return any(word in NEGATIONS for word in preceding)


def match_escalation(user_input, rules=None, categories=None):
    """Return (category, matched_text) for the first rule that fires, else None."""
    rules = DEFAULT_RULES if rules is None else rules
    for code, (_, patterns) in rules.items():
        if categories is not None and code not in categories:
            continue
        for pattern in patterns:
            for match in pattern.finditer(user_input):
                if not _is_negated(user_input, match.start()):
                    return code, match.group(0)
    return None


def check_escalation(user_input, rules=None):
    """Return (True, reason) if the message must go to a human, else (False, None)."""
    hit = match_escalation(user_input, rules)
    if hit is None:
        return False, None
    code, matched = hit
    return True, f"{label_for(code, rules)} (matched '{matched}')"
