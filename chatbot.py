"""Conversation router for the Bloom Aesthetics support agent.

Every message goes through two steps:

  decide()   -> a Decision: what to do and why (action, category, source, confidence)
  execute()  -> carries the decision out and returns a Reply

Deciding (ROUTER_MODE=llm, the default):
  1. "summary" command                       -> summary            (deterministic)
  2. Guardrail rules (medical, legal)        -> escalate           (always win)
  3. LLM intent classifier, confidence >= threshold -> act on its intent
  4. Classifier failed or low confidence     -> rule-based decision (fallback)

ROUTER_MODE=rules skips step 3 and is used as the baseline in evals.
"""

import logging
import os
import re
from dataclasses import dataclass, field

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

import classifier
from escalation import GUARDRAIL_CATEGORIES, label_for, match_escalation
from lead_qualification import LEAD_QUESTIONS
from prompts import NO_ANSWER_TOKEN, SYSTEM_PROMPT
from sop_data import SOP, SOP_TOPICS
from summary import generate_summary

load_dotenv()

logger = logging.getLogger("closira.agent")

MAX_UNANSWERED = 2          # SOP: escalate if more than 2 unanswered questions
HISTORY_WINDOW = 10         # messages of context sent to the answering LLM

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

ESCALATION_INTENTS = {"complaint", "human_request", "legal", "medical", "price_negotiation"}

GREETING_REPLY = (
    "Hello! Welcome to Bloom Aesthetics Clinic. I can help with our treatments, "
    "prices, opening hours, booking and cancellations. What would you like to know?"
)
THANKS_REPLY = "You're welcome! Is there anything else I can help with?"
HELP_REPLY = (
    "I can help with our treatments, prices, opening hours, booking and cancellations. "
    "What would you like to know?"
)
NOT_IN_SOP_REPLY = (
    "I'm sorry, I don't have that information. "
    "I've noted your question so our team can follow up with you."
)
ESCALATION_REPLIES = {
    "medical": (
        "For your safety, medical questions are answered by our clinicians. "
        "I've passed your question to the team and someone will contact you shortly."
    ),
    "price_negotiation": (
        "Our prices start from £200 for Botox and £250 for fillers. "
        "I've passed your request to our team, who can discuss pricing with you."
    ),
    "unanswered_limit": (
        "I'm sorry I haven't been able to answer your questions. "
        "I've passed this conversation to a member of our team, who will get back to you shortly."
    ),
    "error": (
        "Sorry, I'm having trouble answering right now. "
        "I've passed your message to our team, who will get back to you shortly."
    ),
}
DEFAULT_ESCALATION_REPLY = (
    "I'm sorry to hear that. I've passed your conversation to a member of our team, "
    "who will get back to you shortly."
)


@dataclass
class Decision:
    action: str                      # summary|escalate|greeting|thanks|smalltalk|lead_answer|faq|unanswered
    source: str                      # command|guardrail|llm|rules|rules_fallback
    category: str | None = None      # escalation category when action == "escalate"
    detail: str | None = None        # e.g. matched keyword
    confidence: float | None = None  # classifier confidence, when the LLM decided
    topics: list = field(default_factory=list)


@dataclass
class Reply:
    text: str
    route: str                       # what actually happened (see execute())
    escalated: bool = False
    category: str | None = None
    reason: str | None = None
    source: str | None = None
    confidence: float | None = None


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


def router_mode():
    return os.getenv("ROUTER_MODE", "llm").lower()


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


# ---------------------------------------------------------------------------
# Decide
# ---------------------------------------------------------------------------

def decide_rules(state, user_input, source="rules"):
    """Deterministic routing: keyword rules + simple heuristics."""
    hit = match_escalation(user_input)
    if hit:
        return Decision("escalate", source, category=hit[0], detail=f"matched '{hit[1]}'")
    if GREETING_RE.match(user_input):
        return Decision("greeting", source)
    if THANKS_RE.match(user_input):
        return Decision("thanks", source)

    question = is_question(user_input)
    if state.pending_question and not question:
        return Decision("lead_answer", source)

    topics = match_topics(user_input)
    if topics:
        return Decision("faq", source, topics=topics)
    if question:
        return Decision("unanswered", source)
    return Decision("smalltalk", source)


def _decision_from_classification(state, result):
    intent, conf = result.intent, result.confidence
    topics = list(result.topics)

    if intent in ESCALATION_INTENTS:
        return Decision("escalate", "llm", category=intent, detail=f"intent={intent}", confidence=conf)
    if intent == "lead_answer":
        action = "lead_answer" if state.pending_question else "smalltalk"
        return Decision(action, "llm", confidence=conf)
    if intent == "out_of_scope":
        return Decision("unanswered", "llm", confidence=conf)
    if intent == "faq":
        return Decision("faq", "llm", confidence=conf, topics=topics)
    return Decision(intent, "llm", confidence=conf)  # greeting | thanks | smalltalk


def decide(state, user_input):
    if SUMMARY_RE.match(user_input):
        return Decision("summary", "command")

    guardrail = match_escalation(user_input, categories=GUARDRAIL_CATEGORIES)
    if guardrail:
        return Decision("escalate", "guardrail", category=guardrail[0], detail=f"matched '{guardrail[1]}'")

    if router_mode() != "llm":
        return decide_rules(state, user_input)

    try:
        result = classifier.classify(state)
    except Exception:
        logger.exception("Classifier failed session=%s; using rules", state.session_id)
        return decide_rules(state, user_input, source="rules_fallback")

    logger.info(
        "CLASSIFY session=%s intent=%s confidence=%.2f topics=%s",
        state.session_id, result.intent, result.confidence, result.topics,
    )
    if result.confidence < classifier.CONFIDENCE_THRESHOLD:
        decision = decide_rules(state, user_input, source="rules_fallback")
        decision.detail = f"low confidence {result.intent}@{result.confidence:.2f}"
        return decision

    return _decision_from_classification(state, result)


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------

def _with_pending_question(state, text):
    """Append the outstanding lead question (if any) so the flow keeps moving."""
    pending = state.pending_question
    if pending:
        return f"{text}\n\n{pending[1]}"
    return text


def _escalate(state, decision, category=None):
    category = category or decision.category
    reason = label_for(category)
    if decision.detail and category == decision.category:
        reason += f" ({decision.detail})"
    state.escalations.append(reason)
    logger.warning(
        "ESCALATION session=%s category=%s source=%s reason=%s",
        state.session_id, category, decision.source, reason,
    )
    return Reply(
        ESCALATION_REPLIES.get(category, DEFAULT_ESCALATION_REPLY),
        route="escalated", escalated=True, category=category, reason=reason,
    )


def _record_unanswered(state, decision, user_input):
    state.unanswered.append(user_input)
    logger.info("SOP_GAP session=%s question=%r", state.session_id, user_input)
    if len(state.unanswered) > MAX_UNANSWERED:
        return _escalate(state, decision, category="unanswered_limit")
    return Reply(_with_pending_question(state, NOT_IN_SOP_REPLY), route="sop_gap")


def _record_lead_answer(state, user_input):
    field_name, _ = LEAD_QUESTIONS[state.lead_index]
    state.lead[field_name] = user_input
    state.lead_index += 1
    logger.info("LEAD session=%s %s=%r", state.session_id, field_name, user_input)

    if state.pending_question:
        return Reply(state.pending_question[1], route="lead_answer")

    name = state.lead.get("name", "").split()[0] if state.lead.get("name") else ""
    return Reply(
        f"Thank you{', ' + name if name else ''}! Our team will contact you to confirm your booking.\n\n"
        "Type 'summary' to see a summary of this conversation.",
        route="lead_answer",
    )


def _answer_faq(state, decision, user_input):
    try:
        answer = answer_from_sop(state)
    except Exception:
        logger.exception("LLM call failed session=%s", state.session_id)
        return _escalate(state, decision, category="error")

    if answer is None:
        return _record_unanswered(state, decision, user_input)

    topics = decision.topics or match_topics(user_input)
    state.topics.extend(t for t in topics if t not in state.topics)
    if not state.qualification_started:
        state.lead_index = 0
        return Reply(f"{answer}\n\nI'd be happy to help you book. {LEAD_QUESTIONS[0][1]}", route="answered")
    return Reply(_with_pending_question(state, answer), route="answered")


def execute(state, decision, user_input):
    action = decision.action
    if action == "summary":
        return Reply(generate_summary(state), route="summary")
    if action == "escalate":
        return _escalate(state, decision)
    if action == "greeting":
        return Reply(_with_pending_question(state, GREETING_REPLY), route="greeting")
    if action == "thanks":
        return Reply(_with_pending_question(state, THANKS_REPLY), route="thanks")
    if action == "lead_answer":
        return _record_lead_answer(state, user_input)
    if action == "faq":
        return _answer_faq(state, decision, user_input)
    if action == "unanswered":
        return _record_unanswered(state, decision, user_input)
    return Reply(_with_pending_question(state, HELP_REPLY), route="smalltalk")


def get_response(state, user_input):
    """Process one user message for the given conversation state and return a Reply."""
    user_input = user_input.strip()
    state.add("user", user_input)

    decision = decide(state, user_input)
    reply = execute(state, decision, user_input)
    reply.source, reply.confidence = decision.source, decision.confidence

    state.add("assistant", reply.text)
    return reply
