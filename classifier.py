"""LLM intent classifier with structured output.

The model returns a typed Classification (intent + confidence + SOP topics),
validated by Pydantic. The topic list is built per business from its config.
The router acts on the result only when confidence is at or above
CONFIDENCE_THRESHOLD; otherwise it falls back to the deterministic rules.
"""

import os
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, create_model

CONFIDENCE_THRESHOLD = float(os.getenv("CLASSIFIER_CONFIDENCE_THRESHOLD", "0.6"))
CONTEXT_MESSAGES = 4

Intent = Literal[
    "greeting", "thanks", "smalltalk",
    "faq", "out_of_scope", "lead_answer",
    "complaint", "human_request", "legal", "medical", "price_negotiation",
]


class Classification(BaseModel):
    """Base schema. Per-business subclasses narrow `topics` to that business's SOP topics."""
    intent: Intent = Field(description="The single best intent for the latest customer message.")
    confidence: float = Field(ge=0, le=1, description="Probability that the intent is correct.")
    topics: list[str] = Field(default_factory=list, description="SOP topics the message is about.")


def classification_model(business):
    topic = Literal[tuple(business.topics)]
    return create_model(
        f"Classification_{business.id}",
        __base__=Classification,
        topics=(list[topic], Field(default_factory=list, description="SOP topics the message is about.")),
    )


def build_prompt(business):
    return f"""You route messages for the customer support assistant of {business.name}.
Classify ONLY the latest customer message, using earlier messages as context.

The business SOP (the only information the assistant may give):
{business.sop}

Intents:
- greeting: just a hello, with no question.
- thanks: just thanks / acknowledgement.
- smalltalk: anything else that is not a question and needs no action (e.g. "ok", "cool").
- faq: a question or request the SOP above can answer (hours, services offered, prices, booking, cancellation...).
  Asking what something costs is faq.
- out_of_scope: a question about something the SOP does not cover.
- lead_answer: the customer is answering the assistant's pending question (shown below), e.g. giving a name, treatment, time or phone number.
- complaint: dissatisfaction, frustration, a refund or money-back request. Negated statements ("I'm not angry") are NOT complaints.
- human_request: asks to speak to a person, manager or staff member.
- legal: threatens legal action or mentions lawyers/solicitors.
- medical: anything about health, safety, suitability, side effects, pain, recovery, aftercare, pregnancy, medications or symptoms.
- price_negotiation: asks for a discount, deal, lower price or a specific price below the listed one.

If a message fits several intents, prefer in this order: medical, legal, complaint, human_request, price_negotiation,
then the rest. Set confidence honestly; use a low value when the message is ambiguous."""


_classifiers = {}


def _get_classifier(business):
    if business.id not in _classifiers:
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
        _classifiers[business.id] = (
            llm.with_structured_output(classification_model(business), method="json_schema"),
            build_prompt(business),
        )
    return _classifiers[business.id]


def classify(state):
    """Classify the latest user message in state.transcript."""
    chain, prompt = _get_classifier(state.business)
    pending = state.pending_field
    context_lines = [
        f"{'Customer' if role == 'user' else 'Assistant'}: {text}"
        for role, text in state.transcript[-(CONTEXT_MESSAGES + 1):-1]
    ]
    latest = state.transcript[-1][1]

    user_prompt = (
        "Recent conversation:\n" + ("\n".join(context_lines) or "(none)") + "\n\n"
        f"Pending question the customer may be answering: {pending.question if pending else '(none)'}\n\n"
        f"Latest customer message: {latest}"
    )
    return chain.invoke([SystemMessage(content=prompt), HumanMessage(content=user_prompt)])
