"""LLM intent classifier with structured output.

The model returns a typed Classification (intent + confidence + SOP topics),
validated by Pydantic. The router acts on it only when confidence is at or
above CONFIDENCE_THRESHOLD; otherwise it falls back to the deterministic rules.
"""

import os
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from sop_data import SOP, SOP_TOPICS

CONFIDENCE_THRESHOLD = float(os.getenv("CLASSIFIER_CONFIDENCE_THRESHOLD", "0.6"))
CONTEXT_MESSAGES = 4

Intent = Literal[
    "greeting", "thanks", "smalltalk",
    "faq", "out_of_scope", "lead_answer",
    "complaint", "human_request", "legal", "medical", "price_negotiation",
]
Topic = Literal[tuple(SOP_TOPICS)]


class Classification(BaseModel):
    intent: Intent = Field(description="The single best intent for the latest customer message.")
    confidence: float = Field(ge=0, le=1, description="Probability that the intent is correct.")
    topics: list[Topic] = Field(default_factory=list, description="SOP topics the message is about.")


CLASSIFIER_PROMPT = f"""You route messages for the customer support assistant of Bloom Aesthetics Clinic.
Classify ONLY the latest customer message, using earlier messages as context.

The clinic SOP (the only information the assistant may give):
{SOP}

Intents:
- greeting: just a hello, with no question.
- thanks: just thanks / acknowledgement.
- smalltalk: anything else that is not a question and needs no action (e.g. "ok", "cool").
- faq: a question or request the SOP above can answer (hours, services offered, prices, booking, cancellation, consultations).
  Asking what something costs is faq.
- out_of_scope: a question about something the SOP does not cover (other treatments, parking, payment methods, staff, location...).
- lead_answer: the customer is answering the assistant's pending question (shown below), e.g. giving a name, treatment, time or phone number.
- complaint: dissatisfaction, frustration, a refund or money-back request. Negated statements ("I'm not angry") are NOT complaints.
- human_request: asks to speak to a person, manager or staff member.
- legal: threatens legal action or mentions lawyers/solicitors.
- medical: anything about health, safety, suitability, side effects, recovery, aftercare, pregnancy, medications or symptoms.
- price_negotiation: asks for a discount, deal, lower price or a specific price below the listed one.

If a message fits several intents, prefer in this order: medical, legal, complaint, human_request, price_negotiation,
then the rest. Set confidence honestly; use a low value when the message is ambiguous."""


_classifier = None


def _get_classifier():
    global _classifier
    if _classifier is None:
        from langchain_groq import ChatGroq

        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is not set")
        llm = ChatGroq(
            api_key=api_key,
            # 20b matched 120b's accuracy at lower latency; see evals/results.md
            model=os.getenv("GROQ_CLASSIFIER_MODEL", "openai/gpt-oss-20b"),
            temperature=0,
            timeout=15,
            max_retries=2,
        )
        _classifier = llm.with_structured_output(Classification, method="json_schema")
    return _classifier


def classify(state):
    """Classify the latest user message in state.transcript."""
    pending = state.pending_question
    context_lines = [
        f"{'Customer' if role == 'user' else 'Assistant'}: {text}"
        for role, text in state.transcript[-(CONTEXT_MESSAGES + 1):-1]
    ]
    latest = state.transcript[-1][1]

    user_prompt = (
        "Recent conversation:\n" + ("\n".join(context_lines) or "(none)") + "\n\n"
        f"Pending question the customer may be answering: {pending[1] if pending else '(none)'}\n\n"
        f"Latest customer message: {latest}"
    )
    return _get_classifier().invoke([
        SystemMessage(content=CLASSIFIER_PROMPT),
        HumanMessage(content=user_prompt),
    ])
