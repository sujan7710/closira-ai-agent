"""Routing, state and API tests. The LLM is replaced by a fake so tests are fast and offline."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chatbot  # noqa: E402
from conversation import ConversationState  # noqa: E402
from escalation import check_escalation  # noqa: E402
from business import get_business  # noqa: E402

NAME_Q = get_business("bloom").lead_field("name").question


@pytest.fixture(autouse=True)
def fake_llm(monkeypatch):
    """Answer known SOP questions; return None (not in SOP) otherwise.

    Also defaults the router to rules mode and makes the real classifier
    unreachable, so no test can hit the network by accident.
    """
    calls = []
    monkeypatch.setenv("ROUTER_MODE", "rules")

    def no_network(state):
        raise AssertionError("real classifier called in a test")

    monkeypatch.setattr(chatbot.classifier, "classify", no_network)

    def fake_answer(state):
        question = state.transcript[-1][1].lower()
        calls.append(question)
        if "botox" in question:
            return "Botox starts from £200."
        if "open" in question or "hours" in question:
            return "We're open Mon–Sat, 9 am–7 pm."
        if "book" in question:
            return "You can book via WhatsApp or our website."
        return None

    monkeypatch.setattr(chatbot, "answer_from_sop", fake_answer)
    return calls


def new_state(sid="s1"):
    return ConversationState(session_id=sid)


def say(state, text):
    return chatbot.get_response(state, text)


# --- escalation rules -------------------------------------------------------

@pytest.mark.parametrize("text", [
    "I am angry about your terrible service",
    "I want a refund",
    "Can I speak to a manager?",
    "Is Botox safe during pregnancy?",
    "Can I get a discount on fillers?",
    "I'll sue the clinic",
])
def test_escalates(text):
    assert check_escalation(text)[0] is True


@pytest.mark.parametrize("text", [
    "I'm not angry, just curious about Botox",
    "What are your opening hours?",
    "Sue",                       # a customer's name, not a legal threat
    "Do you offer fillers?",
])
def test_does_not_escalate(text):
    assert check_escalation(text)[0] is False


def test_medical_question_escalates_before_llm(fake_llm):
    state = new_state()
    reply = say(state, "Is Botox safe while breastfeeding?")
    assert reply.escalated and reply.reason.startswith("Medical question")
    assert fake_llm == []  # never reached the LLM
    assert state.escalations


# --- routing -----------------------------------------------------------------

def test_greeting_is_not_escalated():
    reply = say(new_state(), "Hello!")
    assert not reply.escalated
    assert "Welcome" in reply.text


def test_opening_hours_answered():
    reply = say(new_state(), "When are you open?")
    assert "9 am" in reply.text


def test_out_of_scope_logged_as_gap():
    state = new_state()
    reply = say(state, "Do you provide dental surgery?")
    assert not reply.escalated
    assert state.unanswered == ["Do you provide dental surgery?"]


def test_llm_sentinel_counts_as_gap():
    state = new_state()
    say(state, "Do you offer laser hair removal services?")  # topic keyword hit, LLM says not in SOP
    assert len(state.unanswered) == 1


def test_third_unanswered_question_escalates():
    state = new_state()
    assert not say(state, "Do you do dental work?").escalated
    assert not say(state, "Do you sell gift cards?").escalated
    reply = say(state, "Is there parking nearby?")
    assert reply.escalated and "More than 2 unanswered" in reply.reason


def test_llm_failure_escalates_gracefully(monkeypatch):
    def boom(state):
        raise RuntimeError("Groq down")

    monkeypatch.setattr(chatbot, "answer_from_sop", boom)
    reply = say(new_state(), "How much is Botox?")
    assert reply.escalated and "LLM unavailable" in reply.reason


# --- lead qualification ---------------------------------------------------------

def test_full_lead_flow_and_summary():
    state = new_state()
    first = say(state, "How much is Botox?")
    assert "£200" in first.text and NAME_Q in first.text

    say(state, "Sam Patel")
    say(state, "Botox")  # topic keyword, but it's an answer to the pending question
    say(state, "Saturday 3pm")
    done = say(state, "07700 900123")
    assert "Thank you, Sam" in done.text
    assert state.lead == {
        "name": "Sam Patel", "treatment": "Botox",
        "preferred_time": "Saturday 3pm", "contact": "07700900123",
    }

    summary = say(state, "summary").text
    assert "Lead qualification (Complete)" in summary
    assert "botox" in summary and "pricing" in summary
    assert "Contact Sam Patel on 07700900123" in summary


def test_question_during_qualification_reasks_pending_question():
    state = new_state()
    say(state, "How much is Botox?")
    reply = say(state, "How do I book?")
    assert "WhatsApp" in reply.text
    assert reply.text.endswith(NAME_Q)
    assert state.lead == {}


def test_summary_reflects_escalation_and_gaps():
    state = new_state()
    say(state, "Do you do dental work?")
    say(state, "This is terrible service")
    summary = say(state, "summary").text
    assert "Do you do dental work?" in summary
    assert "Complaint or frustration" in summary
    assert "Human agent to follow up" in summary


# --- sessions & API ----------------------------------------------------------------

def test_sessions_are_isolated():
    from app import app

    a, b = app.test_client(), app.test_client()
    a.post("/chat", json={"message": "How much is Botox?"})
    a.post("/chat", json={"message": "Sam"})

    summary_b = b.post("/chat", json={"message": "summary"}).get_json()["response"]
    assert "Sam" not in summary_b
    assert "Not started" in summary_b

    summary_a = a.post("/chat", json={"message": "summary"}).get_json()["response"]
    assert "Name: Sam" in summary_a


@pytest.mark.parametrize("payload", [None, {}, {"message": ""}, {"message": 42}, {"message": "x" * 1001}])
def test_chat_rejects_bad_input(payload):
    from app import app

    client = app.test_client()
    res = client.post("/chat", json=payload) if payload is not None else client.post("/chat", data="nope")
    assert res.status_code == 400


def test_escalation_flag_in_api_response():
    from app import app

    data = app.test_client().post("/chat", json={"message": "I want to speak to a manager"}).get_json()
    assert data["escalated"] is True
    assert "human" in data["reason"].lower()
