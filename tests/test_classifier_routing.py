"""Routing tests for ROUTER_MODE=llm, with a fake classifier."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chatbot  # noqa: E402
from classifier import Classification  # noqa: E402
from conversation import ConversationState  # noqa: E402


@pytest.fixture
def llm_mode(monkeypatch):
    """Switch to LLM routing. Returns a setter for the classifier's next result."""
    monkeypatch.setenv("ROUTER_MODE", "llm")
    monkeypatch.setattr(chatbot, "answer_from_sop", lambda state: "We're open Mon–Sat, 9 am–7 pm.")
    box = {}

    def fake_classify(state):
        if isinstance(box.get("result"), Exception):
            raise box["result"]
        return box["result"]

    monkeypatch.setattr(chatbot.classifier, "classify", fake_classify)
    # Extraction: return the message as the pending field's value.
    monkeypatch.setattr(
        chatbot.extractor, "extract", lambda state, msg: {state.pending_field.name: msg}
    )

    def set_result(intent=None, confidence=0.95, topics=(), error=None):
        box["result"] = error or Classification(intent=intent, confidence=confidence, topics=list(topics))

    return set_result


def say(state, text):
    return chatbot.get_response(state, text)


def test_classifier_catches_complaint_rules_miss(llm_mode):
    llm_mode("complaint", 0.9)
    reply = say(ConversationState("s"), "I've waited three days for a reply, this is ridiculous")
    assert reply.escalated and reply.category == "complaint"
    assert reply.source == "llm" and reply.confidence == 0.9


def test_classifier_routes_faq_without_keywords(llm_mode):
    llm_mode("faq", 0.92, topics=["opening hours"])
    state = ConversationState("s")
    reply = say(state, "Can I come in at 8pm?")
    assert reply.route == "answered"
    assert state.topics == ["opening hours"]


def test_classifier_out_of_scope_is_gap(llm_mode):
    llm_mode("out_of_scope", 0.9)
    state = ConversationState("s")
    reply = say(state, "Do you have parking?")
    assert reply.route == "sop_gap" and state.unanswered == ["Do you have parking?"]


def test_low_confidence_falls_back_to_rules(llm_mode):
    llm_mode("complaint", 0.3)  # wrong and unsure -> rules decide
    reply = say(ConversationState("s"), "When are you open?")
    assert reply.route == "answered"
    assert reply.source == "rules_fallback"


def test_classifier_error_falls_back_to_rules(llm_mode):
    llm_mode(error=RuntimeError("Groq down"))
    reply = say(ConversationState("s"), "I want a refund")
    assert reply.escalated and reply.category == "complaint"
    assert reply.source == "rules_fallback"


def test_guardrail_overrides_classifier(llm_mode):
    llm_mode("faq", 0.99)  # classifier thinks it's a normal question
    reply = say(ConversationState("s"), "Is Botox safe during pregnancy?")
    assert reply.escalated and reply.category == "medical"
    assert reply.source == "guardrail"


def test_lead_answer_only_when_question_pending(llm_mode):
    llm_mode("lead_answer", 0.9)
    state = ConversationState("s")
    assert say(state, "Sam").route == "smalltalk"   # nothing pending
    state.start_lead_at("name")
    assert say(state, "Sam").route == "lead_answer"
    assert state.lead["name"] == "Sam"


def test_summary_command_never_calls_classifier(llm_mode):
    llm_mode(error=AssertionError("should not be called"))
    assert say(ConversationState("s"), "summary").route == "summary"


def test_api_exposes_routing_trace(llm_mode):
    from app import app

    llm_mode("price_negotiation", 0.88)
    data = app.test_client().post("/chat", json={"message": "Can you do Botox for £150?"}).get_json()
    assert data["escalated"] and data["category"] == "price_negotiation"
    assert data["source"] == "llm" and data["confidence"] == 0.88
