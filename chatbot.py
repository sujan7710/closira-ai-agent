"""Conversation router for the Bloom Aesthetics support agent.

Routing order for every message:
  1. "summary" command            -> structured conversation summary
  2. Escalation rules             -> handoff to a human (complaint, medical, negotiation, ...)
  3. Greeting / thanks only       -> friendly canned reply
  4. Pending lead question        -> record the answer, ask the next one
  5. Mentions an SOP topic        -> LLM answer grounded in the SOP (or sentinel if not covered)
  6. Any other question           -> logged as an SOP gap; 3rd gap escalates
  7. Anything else                -> offer help with what the SOP covers
"""

import logging
import os
import re
from dataclasses import dataclass

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from escalation import check_escalation
from lead_qualification import LEAD_QUESTIONS
from prompts import NO_ANSWER_TOKEN, SYSTEM_PROMPT
from sop_data import SOP, SOP_TOPICS
from summary import generate_summary

load_dotenv()

logger = logging.getLogger("closira.agent")

MAX_UNANSWERED = 2          # SOP: escalate if more than 2 unanswered questions
HISTORY_WINDOW = 10         # messages of context sent to the LLM

QUESTION_WORDS = {
    "what", "how", "do", "does", "did", "can", "could", "would", "will", "should",
    "is", "are", "where", "when", "why", "which", "who", "any",
}
GREETING_RE = re.compile(
    r"^(hi|hello|hey|hiya|good (morning|afternoon|evening))( there)?[\s!.,]*$", re.IGNORECASE
)
THANKS_RE = re.compile(r"^(thanks|thank you|cheers|ok(ay)? thanks?)( (so|very) much)?[\s!.,]*$", re.IGNORECASE)
SUMMARY_RE = re.compile(r"^summary[\s!.?]*$", re.IGNORECASE)

_TOPIC_PATTERNS = {
    topic: [re.compile(rf"(?<!\w){p}(?!\w)", re.IGNORECASE) for p in patterns]
    for topic, patterns in SOP_TOPICS.items()
}

NOT_IN_SOP_REPLY = (
    "I'm sorry, I don't have that information. "
    "I've noted your question so our team can follow up with you."
)
ERROR_REPLY = (
    "Sorry, I'm having trouble answering right now. "
    "I've passed your message to our team, who will get back to you shortly."
)


@dataclass
class Reply:
    text: str
    escalated: bool = False
    reason: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_question(text):
    text = text.strip().lower()
    if "?" in text:
        return True
    words = re.findall(r"[a-z']+", text)
    return bool(words) and words[0] in QUESTION_WORDS


def match_topics(text):
    return [
        topic for topic, patterns in _TOPIC_PATTERNS.items()
        if any(p.search(text) for p in patterns)
    ]


_llm = None


def _get_llm():
    global _llm
    if _llm is None:
        from langchain_groq import ChatGroq

        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is not set")
        _llm = ChatGroq(
            api_key=api_key,
            model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
            temperature=0,
            timeout=20,
            max_retries=2,
        )
    return _llm


def answer_from_sop(state):
    """Ask the LLM to answer the latest user message using only the SOP.

    Returns the answer text, or None if the SOP does not cover the question.
    """
    messages = [SystemMessage(content=SYSTEM_PROMPT + "\n\nSOP DATA:\n" + SOP)]
    for role, text in state.transcript[-HISTORY_WINDOW:]:
        messages.append(HumanMessage(content=text) if role == "user" else AIMessage(content=text))

    answer = _get_llm().invoke(messages).content.strip()
    if NO_ANSWER_TOKEN in answer:
        return None
    return answer


def _with_pending_question(state, text):
    """Append the outstanding lead question (if any) so the flow keeps moving."""
    pending = state.pending_question
    if pending:
        return f"{text}\n\n{pending[1]}"
    return text


def _escalate(state, reason, customer_text=None):
    state.escalations.append(reason)
    logger.warning("ESCALATION session=%s reason=%s", state.session_id, reason)
    if customer_text is None:
        if reason.startswith("Medical question"):
            customer_text = (
                "For your safety, medical questions are answered by our clinicians. "
                "I've passed your question to the team and someone will contact you shortly."
            )
        elif reason.startswith("Pricing negotiation"):
            customer_text = (
                "Our prices start from £200 for Botox and £250 for fillers. "
                "I've passed your request to our team, who can discuss pricing with you."
            )
        else:
            customer_text = (
                "I'm sorry to hear that. I've passed your conversation to a member of our team, "
                "who will get back to you shortly."
            )
    return Reply(customer_text, escalated=True, reason=reason)


def _record_unanswered(state, user_input):
    state.unanswered.append(user_input)
    logger.info("SOP_GAP session=%s question=%r", state.session_id, user_input)
    if len(state.unanswered) > MAX_UNANSWERED:
        return _escalate(
            state,
            f"More than {MAX_UNANSWERED} unanswered questions",
            "I'm sorry I haven't been able to answer your questions. "
            "I've passed this conversation to a member of our team, who will get back to you shortly.",
        )
    return Reply(_with_pending_question(state, NOT_IN_SOP_REPLY))


def _record_lead_answer(state, user_input):
    field_name, _ = LEAD_QUESTIONS[state.lead_index]
    state.lead[field_name] = user_input
    state.lead_index += 1
    logger.info("LEAD session=%s %s=%r", state.session_id, field_name, user_input)

    if state.pending_question:
        return Reply(state.pending_question[1])

    name = state.lead.get("name", "").split()[0] if state.lead.get("name") else ""
    return Reply(
        f"Thank you{', ' + name if name else ''}! Our team will contact you to confirm your booking.\n\n"
        "Type 'summary' to see a summary of this conversation."
    )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def _route(state, user_input):
    if SUMMARY_RE.match(user_input):
        return Reply(generate_summary(state))

    escalate, reason = check_escalation(user_input)
    if escalate:
        return _escalate(state, reason)

    if GREETING_RE.match(user_input):
        return Reply(_with_pending_question(
            state,
            "Hello! Welcome to Bloom Aesthetics Clinic. I can help with our treatments, "
            "prices, opening hours, booking and cancellations. What would you like to know?",
        ))
    if THANKS_RE.match(user_input):
        return Reply(_with_pending_question(state, "You're welcome! Is there anything else I can help with?"))

    question = is_question(user_input)

    if state.pending_question and not question:
        return _record_lead_answer(state, user_input)

    topics = match_topics(user_input)
    if topics:
        try:
            answer = answer_from_sop(state)
        except Exception:
            logger.exception("LLM call failed session=%s", state.session_id)
            return _escalate(state, "Assistant error (LLM unavailable)", ERROR_REPLY)

        if answer is None:
            return _record_unanswered(state, user_input)

        state.topics.extend(t for t in topics if t not in state.topics)
        if not state.qualification_started:
            state.lead_index = 0
            return Reply(f"{answer}\n\nI'd be happy to help you book. {LEAD_QUESTIONS[0][1]}")
        return Reply(_with_pending_question(state, answer))

    if question:
        return _record_unanswered(state, user_input)

    return Reply(_with_pending_question(
        state,
        "I can help with our treatments, prices, opening hours, booking and cancellations. "
        "What would you like to know?",
    ))


def get_response(state, user_input):
    """Process one user message for the given conversation state and return a Reply."""
    user_input = user_input.strip()
    state.add("user", user_input)
    reply = _route(state, user_input)
    state.add("assistant", reply.text)
    return reply
