# Closira AI Customer Support Agent

An AI support agent for a small business (Bloom Aesthetics Clinic). It answers FAQs strictly from the clinic's SOP, qualifies leads for booking, hands off to a human when the SOP says it must, and produces a structured summary for the team.

Built with Flask, LangChain and Groq (`openai/gpt-oss-120b` by default).

## Features

- **SOP-grounded answers.** The LLM may only use facts from the SOP. If the SOP doesn't cover a question, the model returns a sentinel token (`NO_SOP_ANSWER`) and the code shows a fixed reply. The model never writes free text for questions it can't answer.
- **Rule-based escalation that runs before the LLM.** Complaints, requests for a human, legal threats, medical questions and pricing negotiation are all handed off without calling the model. Negations are handled ("I'm not angry" does not escalate).
- **SOP gap tracking.** Unanswered questions are logged. On the third one the conversation escalates, as the SOP requires ("more than 2 unanswered questions").
- **Lead qualification.** After the first answered question, the agent collects name, treatment, preferred time and contact. If the customer asks something mid-flow, it answers and then repeats the pending question.
- **Structured summary.** Built from the tracked state: topics, lead details, SOP gaps, escalation reasons and a recommended next action.
- **Per-user sessions.** Each browser gets its own conversation through a signed session cookie.
- **Safe UI.** Messages are rendered with `textContent` (no XSS). Errors and escalation badges are shown. There are New chat and Summary buttons.
- **Logging.** Every escalation, SOP gap and lead field is logged with its session ID.

## Message routing

```
message
  ├─ "summary"                      → structured summary
  ├─ escalation rule matched         → handoff to human (reason logged)
  ├─ greeting / thanks only          → canned reply
  ├─ answering a pending lead question → store answer, ask the next one
  ├─ mentions an SOP topic           → LLM answer from the SOP (sentinel → SOP gap)
  ├─ other question                  → SOP gap (3rd gap → escalate)
  └─ anything else                   → offer help
```

## Project structure

```
app.py                 Flask app: /, /chat, /reset; input validation, sessions
chatbot.py             Message router and LLM call
conversation.py        ConversationState + thread-safe in-memory SessionStore
escalation.py          Escalation rules with negation handling
lead_qualification.py  Lead questions and field labels
summary.py             Structured summary from conversation state
prompts.py             System prompt and NO_SOP_ANSWER sentinel
sop_data.py            SOP text and topic keywords
templates/, static/    Chat UI
tests/                 pytest suite (LLM mocked, runs offline)
test_transcripts/      Sample conversations recorded against the real model
scripts/check_groq.py  Checks that your Groq API key works
```

## Setup

```bash
python -m venv venv
venv\Scripts\activate          # Windows  (source venv/bin/activate on macOS/Linux)
pip install -r requirements-dev.txt
```

Create `.env`:

```
GROQ_API_KEY=your_api_key
FLASK_SECRET_KEY=any-long-random-string   # optional; random per process if unset
GROQ_MODEL=openai/gpt-oss-120b            # optional
```

Run:

```bash
python scripts/check_groq.py   # optional: confirm the key works
python app.py                  # http://127.0.0.1:5000  (set FLASK_DEBUG=1 for debug mode)
```

## Tests

```bash
python -m pytest -q
```

The suite covers escalation rules (including negation and false-positive cases), routing, the 3-unanswered-questions rule, LLM failure handling, the full lead flow and summary, session isolation between two clients, and API input validation. The LLM is replaced with a fake, so the tests are fast and need no API key.

## Known limitations / next steps

- Escalation and topic detection use regex rules. Planned next step: an LLM intent classifier with structured output and a confidence threshold.
- Sessions are stored in memory (single process, cleared on restart). Production would use Redis or a database.
- Escalations are logged but don't create tickets yet. Planned: persist handoff tickets and add an admin view.
- The SOP is a Python string. Planned: load it from per-business config (YAML/JSON).

## Author

Sujan M
