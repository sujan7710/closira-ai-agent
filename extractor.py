"""Lead field extraction (LLM) and validation (deterministic).

The LLM pulls any lead fields the customer states in a message, so
"I'm Priya, I'd like fillers on Saturday" fills three fields at once, and
"probably the lip fillers... actually my name is Priya" puts each value in the
right field. Every extracted value is then checked by code: phone numbers must
look like phone numbers, and choices must map to one of the configured options.
The LLM proposes, the validators decide.
"""

import os
import re
from typing import Literal, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import Field, create_model

PHONE_RE = re.compile(r"\+?\d[\d\s\-().]{5,}\d")
YES_WORDS = {"yes", "yeah", "yep", "yup", "sure", "correct", "i have", "already"}
NO_WORDS = {"no", "nope", "never", "not", "first", "new"}


# ---------------------------------------------------------------------------
# Validation (used for both LLM-extracted and raw values)
# ---------------------------------------------------------------------------

def _tokens(text):
    return {w.rstrip("s") for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 2}


def normalize_phone(value):
    match = PHONE_RE.search(value or "")
    if not match:
        return None
    raw = match.group(0)
    digits = re.sub(r"\D", "", raw)
    if not 7 <= len(digits) <= 15:
        return None
    return ("+" if raw.strip().startswith("+") else "") + digits


def normalize_choice(value, options):
    value_l = (value or "").strip().lower()
    if not value_l:
        return None
    for option in options:
        if value_l == option.lower():
            return option

    # Yes/No questions: map common phrasings.
    if {o.lower() for o in options} == {"yes", "no"}:
        words = set(re.findall(r"[a-z]+", value_l))
        if words & NO_WORDS and not value_l.startswith(("yes", "yeah", "yep")):
            return "No"
        if words & YES_WORDS or value_l.startswith(("i have", "i've been")):
            return "Yes"
        return None

    # Otherwise pick the option sharing the most words ("lip fillers" -> "Fillers").
    value_t = _tokens(value_l)
    scored = sorted(((len(_tokens(o) & value_t), o) for o in options), reverse=True)
    if scored and scored[0][0] > 0 and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        return scored[0][1]
    return None


def validate(field, value):
    """Return the normalized value, or None if it is not acceptable for this field."""
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    if field.type == "phone":
        return normalize_phone(value)
    if field.type == "choice":
        return normalize_choice(value, field.options)
    return value[:200]


def invalid_hint(field):
    if field.type == "phone":
        return "Sorry, that doesn't look like a valid phone number. Could you share it again, including the area code?"
    if field.type == "choice":
        options = field.options
        listed = ", ".join(options[:-1]) + f" or {options[-1]}" if len(options) > 1 else options[0]
        return f"Sorry, I didn't catch that. Please choose {listed}."
    return f"Sorry, I didn't catch that. {field.question}"


# ---------------------------------------------------------------------------
# LLM extraction
# ---------------------------------------------------------------------------

def extraction_model(business):
    fields = {}
    for f in business.lead_fields:
        if f.type == "choice":
            ftype = Optional[Literal[tuple(f.options)]]
        else:
            ftype = Optional[str]
        fields[f.name] = (ftype, Field(default=None, description=f.description or f.label))
    return create_model(f"Lead_{business.id}", **fields)


# Note: an earlier "fill a field ONLY if clearly stated" wording made gpt-oss-20b return
# all-null for plain answers like "Saturday morning works" (see evals/extraction_results.md).
EXTRACT_PROMPT = """You extract booking details for {name} from a customer's reply.

Return a value for every field the customer states in their reply, especially the field the
assistant asked about. Use null only for fields the customer did not mention. Never invent values.
Keep values short: a name, not a sentence; the day/time as they said it.
For choice fields, pick the option that best matches what the customer said, or null if none fits."""

_extractors = {}


def _get_extractor(business):
    if business.id not in _extractors:
        from langchain_groq import ChatGroq

        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is not set")
        llm = ChatGroq(
            api_key=api_key,
            model=os.getenv("GROQ_EXTRACTOR_MODEL", os.getenv("GROQ_CLASSIFIER_MODEL", "openai/gpt-oss-20b")),
            temperature=0,
            timeout=15,
            max_retries=2,
        )
        _extractors[business.id] = llm.with_structured_output(extraction_model(business), method="json_schema")
    return _extractors[business.id]


def extract(state, message):
    """Return {field_name: raw_value} for every lead field the LLM found in the message."""
    business = state.business
    pending = state.pending_field
    result = _get_extractor(business).invoke([
        SystemMessage(content=EXTRACT_PROMPT.format(name=business.name)),
        HumanMessage(content=f"Assistant asked: {pending.question if pending else '(nothing)'}\n"
                             f"Customer replied: {message}"),
    ])
    return {k: v for k, v in result.model_dump().items() if v not in (None, "")}
