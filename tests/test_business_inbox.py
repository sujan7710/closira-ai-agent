"""Per-business config, lead extraction/validation, storage and the staff inbox."""

import base64
import re

import pytest
import yaml
from pydantic import ValidationError

import chatbot
import extractor
from business import BusinessConfig, get_business
from conversation import ConversationState
from storage import Storage

BLOOM = get_business("bloom")
DENTAL = get_business("brightside")


@pytest.fixture(autouse=True)
def rules_mode(monkeypatch):
    monkeypatch.setenv("ROUTER_MODE", "rules")
    monkeypatch.setattr(chatbot, "answer_from_sop", lambda state: "We're open Mon–Fri, 8 am–6 pm.")


def say(state, text):
    return chatbot.get_response(state, text)


# --- business config -----------------------------------------------------------------

def test_both_businesses_load():
    assert BLOOM.name == "Bloom Aesthetics Clinic"
    assert DENTAL.name == "Brightside Dental Studio"
    assert "insurance" in DENTAL.guardrail_categories
    assert "insurance" not in BLOOM.escalation_rules


def _raw(path="businesses/bloom.yaml"):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_config_rejects_choice_without_options():
    raw = _raw()
    raw["lead"]["fields"][1]["options"] = []
    with pytest.raises(ValidationError, match="no options"):
        BusinessConfig.model_validate(raw)


def test_config_rejects_unknown_guardrail():
    raw = _raw()
    raw["escalation"]["guardrails"] = ["medical", "astrology"]
    with pytest.raises(ValidationError, match="guardrails not enabled"):
        BusinessConfig.model_validate(raw)


def test_config_rejects_bad_theme_color():
    raw = _raw()
    raw["theme_color"] = "red; background:url(x)"
    with pytest.raises(ValidationError):
        BusinessConfig.model_validate(raw)


def test_dental_custom_guardrail_and_reply():
    reply = say(ConversationState("d", business=DENTAL), "Do you accept Denplan insurance?")
    assert reply.escalated and reply.category == "insurance"
    assert reply.source == "guardrail"
    assert "reception team" in reply.text


def test_dental_specific_medical_patterns():
    reply = say(ConversationState("d", business=DENTAL), "I have a terrible toothache")
    assert reply.escalated
    # Bloom doesn't have dental patterns but 'terrible' is still a complaint there.
    assert say(ConversationState("b", business=BLOOM), "My gums are sore").route != "escalated"


def test_lead_questions_come_from_config():
    state = ConversationState("d", business=DENTAL)
    first = say(state, "What are your opening hours?")
    assert DENTAL.lead_field("name").question in first.text


# --- validators -----------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("07700 900123", "07700900123"),
    ("you can whatsapp me on +44 7700-900-456", "+447700900456"),
    ("(020) 7946 0321", "02079460321"),
    ("call me maybe", None),
    ("123", None),
])
def test_phone_validation(raw, expected):
    assert extractor.normalize_phone(raw) == expected


@pytest.mark.parametrize("raw, options, expected", [
    ("botox", ["Botox", "Fillers", "Free consultation"], "Botox"),
    ("probably the lip fillers", ["Botox", "Fillers", "Free consultation"], "Fillers"),
    ("a free consultation please", ["Botox", "Fillers", "Free consultation"], "Free consultation"),
    ("laser hair removal", ["Botox", "Fillers", "Free consultation"], None),
    ("yes, last year", ["Yes", "No"], "Yes"),
    ("no, this is my first time", ["Yes", "No"], "No"),
    ("never been", ["Yes", "No"], "No"),
    ("hmm", ["Yes", "No"], None),
])
def test_choice_validation(raw, options, expected):
    assert extractor.normalize_choice(raw, options) == expected


# --- lead flow -------------------------------------------------------------------------------

def test_invalid_phone_is_reasked():
    state = ConversationState("b", business=BLOOM)
    state.start_lead_at("contact")
    reply = say(state, "not telling you")
    assert reply.route == "lead_retry"
    assert "valid phone number" in reply.text
    assert "contact" not in state.lead


def test_invalid_choice_lists_options():
    state = ConversationState("b", business=BLOOM)
    state.start_lead_at("treatment")
    reply = say(state, "laser hair removal")
    assert reply.route == "lead_retry"
    assert "Botox, Fillers or Free consultation" in reply.text


def test_llm_extraction_fills_several_fields(monkeypatch):
    monkeypatch.setenv("ROUTER_MODE", "llm")
    monkeypatch.setattr(chatbot.classifier, "classify",
                        lambda s: chatbot.classifier.Classification(intent="lead_answer", confidence=0.95))
    monkeypatch.setattr(chatbot.extractor, "extract",
                        lambda s, m: {"name": "Priya", "treatment": "Fillers", "preferred_time": "Saturday"})
    state = ConversationState("b", business=BLOOM)
    state.start_lead_at("name")
    reply = say(state, "probably the lip fillers... actually my name is Priya, Saturday works")
    assert state.lead == {"name": "Priya", "treatment": "Fillers", "preferred_time": "Saturday"}
    assert reply.text == BLOOM.lead_field("contact").question


def test_extracted_values_are_still_validated(monkeypatch):
    monkeypatch.setenv("ROUTER_MODE", "llm")
    monkeypatch.setattr(chatbot.classifier, "classify",
                        lambda s: chatbot.classifier.Classification(intent="lead_answer", confidence=0.95))
    monkeypatch.setattr(chatbot.extractor, "extract", lambda s, m: {"contact": "12"})
    state = ConversationState("b", business=BLOOM)
    state.start_lead_at("contact")
    assert say(state, "it's 12").route == "lead_retry"


def test_extraction_failure_falls_back_to_raw_answer(monkeypatch):
    monkeypatch.setenv("ROUTER_MODE", "llm")
    monkeypatch.setattr(chatbot.classifier, "classify",
                        lambda s: chatbot.classifier.Classification(intent="lead_answer", confidence=0.95))

    def boom(state, msg):
        raise RuntimeError("Groq down")

    monkeypatch.setattr(chatbot.extractor, "extract", boom)
    state = ConversationState("b", business=BLOOM)
    state.start_lead_at("name")
    say(state, "Sam")
    assert state.lead["name"] == "Sam"


# --- storage ------------------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    return Storage(str(tmp_path / "t.db"))


def test_escalations_in_one_conversation_share_a_ticket(db):
    state = ConversationState("s1", business=BLOOM)
    db.record_turn(state, say(state, "I want a refund"))
    db.record_turn(state, say(state, "Let me speak to a manager"))
    tickets = db.list_tickets()
    assert len(tickets) == 1
    assert len(tickets[0]["reasons"]) == 2
    assert tickets[0]["category"] == "human_request"
    assert len(tickets[0]["transcript"]) == 4


def test_open_ticket_transcript_keeps_updating(db):
    state = ConversationState("s1", business=BLOOM)
    db.record_turn(state, say(state, "I want a refund"))
    db.record_turn(state, say(state, "hello"))
    assert len(db.list_tickets()[0]["transcript"]) == 4


def test_gaps_and_report(db):
    for sid in ("a", "b"):
        state = ConversationState(sid, business=BLOOM)
        db.record_turn(state, say(state, "Do you have parking?"))
    state = ConversationState("c", business=BLOOM)
    db.record_turn(state, say(state, "Do you sell gift vouchers?"))
    report = db.gap_report("bloom")
    assert report[0]["example"] == "Do you have parking?"
    assert report[0]["count"] == 2 and report[0]["conversations"] == 2
    assert db.stats("bloom")["sop_gaps"] == 3


def test_lead_upsert_and_completion(db):
    state = ConversationState("s1", business=BLOOM)
    db.record_turn(state, say(state, "How much is Botox?"))
    for msg in ["Sam", "Botox", "Saturday 3pm", "07700 900123"]:
        db.record_turn(state, say(state, msg))
    leads = db.list_leads("bloom")
    assert len(leads) == 1 and leads[0]["complete"] == 1
    assert leads[0]["fields"]["contact"] == "07700900123"


def test_close_ticket(db):
    state = ConversationState("s1", business=BLOOM)
    db.record_turn(state, say(state, "I want a refund"))
    tid = db.list_tickets()[0]["id"]
    assert db.close_ticket(tid, "Refunded by phone")
    assert db.list_tickets(status="open") == []
    assert db.get_ticket(tid)["resolution"] == "Refunded by phone"
    assert not db.close_ticket(tid, "again")  # already closed


def test_businesses_are_separated(db):
    for biz in (BLOOM, DENTAL):
        state = ConversationState("same-session", business=biz)
        db.record_turn(state, say(state, "I want a refund"))
    assert len(db.list_tickets("bloom")) == 1
    assert len(db.list_tickets("brightside")) == 1


# --- web: pages, inbox auth and security ----------------------------------------------------------

@pytest.fixture
def client():
    from app import app

    return app.test_client()


def test_business_pages(client):
    assert client.get("/").status_code == 302
    page = client.get("/b/brightside").get_data(as_text=True)
    assert "Brightside Dental Studio" in page and "#0f9d8a" in page
    assert client.get("/b/nope").status_code == 404
    assert client.post("/chat", json={"message": "hi", "business": "nope"}).status_code == 400


def test_chat_creates_ticket_visible_in_inbox(client):
    client.post("/chat", json={"message": "I want a refund", "business": "brightside"})
    page = client.get("/admin?business=brightside").get_data(as_text=True)
    assert "Complaint or frustration" in page
    assert "I want a refund" in page


def test_inbox_escapes_customer_text(client):
    client.post("/chat", json={"message": "<script>alert(1)</script> refund now"})
    page = client.get("/admin").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


def test_inbox_local_only_without_password(client):
    assert client.get("/admin").status_code == 200
    assert client.get("/admin", environ_base={"REMOTE_ADDR": "203.0.113.9"}).status_code == 403


def test_inbox_password(client, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    assert client.get("/admin").status_code == 401
    bad = base64.b64encode(b"staff:wrong").decode()
    assert client.get("/admin", headers={"Authorization": f"Basic {bad}"}).status_code == 401
    good = base64.b64encode(b"staff:s3cret").decode()
    assert client.get("/admin", headers={"Authorization": f"Basic {good}"}).status_code == 200


def _ticket_and_token(client):
    client.post("/chat", json={"message": "I want a refund"})
    page = client.get("/admin").get_data(as_text=True)
    token = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
    tid = re.search(r"/admin/tickets/(\d+)/close", page).group(1)
    return tid, token


def test_close_requires_csrf_token(client):
    tid, _ = _ticket_and_token(client)
    assert client.post(f"/admin/tickets/{tid}/close", data={"resolution": "x"}).status_code == 400


def test_close_ticket_via_inbox_and_no_open_redirect(client):
    tid, token = _ticket_and_token(client)
    res = client.post(f"/admin/tickets/{tid}/close",
                      data={"csrf": token, "resolution": "Called back", "next": "https://evil.example"})
    assert res.status_code == 302
    assert "evil.example" not in res.headers["Location"]
    assert "Called back" in client.get("/admin?status=closed").get_data(as_text=True)
