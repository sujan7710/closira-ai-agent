# Closira AI Customer Support Agent

An AI support agent for a small business (Bloom Aesthetics Clinic). It answers FAQs strictly from the clinic's SOP, qualifies leads for booking, hands off to a human when the SOP says it must, and produces a structured summary for the team.

Built with Flask, LangChain and Groq (`openai/gpt-oss-120b` by default).

## Results

On a 52-case routing eval run end to end against the real model ([evals/results.md](evals/results.md)):

| Router | Accuracy | Escalations caught | Cases with no trigger keyword |
|---|---|---|---|
| Keyword rules (v1) | 75% | 7/16 | 1/14 |
| LLM intent classifier (v2) | **98%** | **16/16** | **13/14** |

## Features

- **LLM intent classifier.** Each message is classified into one of 11 intents with a confidence score. The output is a typed Pydantic model returned through Groq's JSON-schema structured output. The classifier sees recent context and any pending lead question, so "Botox" in reply to "Which treatment?" counts as a lead answer, not an FAQ.
- **Confidence threshold with a rule-based fallback.** If the classifier errors or its confidence is below 0.6, the deterministic keyword router decides instead. The agent never stops working because the classifier did.
- **Guardrails.** Medical and legal keyword rules always win, even over a confident classifier. Missing a medical question is far worse than a false alarm.
- **Routing trace.** Every reply carries what happened, who decided (`llm`, `guardrail`, `rules_fallback`) and the classifier's confidence. The trace is returned by the API, shown under each message in the UI, and logged.
- **SOP-grounded answers.** The LLM may only use facts from the SOP. If the SOP doesn't cover a question, the model returns a sentinel token (`NO_SOP_ANSWER`) and the code shows a fixed reply. The model never writes free text for questions it can't answer.
- **Escalation.** Complaints, requests for a human, legal threats, medical questions and pricing negotiation are handed off to a human, with the reason recorded. Negations are handled ("I'm not angry" does not escalate).
- **SOP gap tracking.** Unanswered questions are logged. On the third one the conversation escalates, as the SOP requires ("more than 2 unanswered questions").
- **Lead qualification.** After the first answered question, the agent collects name, treatment, preferred time and contact. If the customer asks something mid-flow, it answers and then repeats the pending question.
- **Structured summary.** Built from the tracked state: topics, lead details, SOP gaps, escalation reasons and a recommended next action.
- **Per-user sessions.** Each browser gets its own conversation through a signed session cookie.
- **Safe UI.** Messages are rendered with `textContent` (no XSS). Errors and escalation badges are shown. There are New chat and Summary buttons.
- **Logging.** Every escalation, SOP gap and lead field is logged with its session ID.

## Message routing

Each message goes through two steps: **decide** (produce a `Decision`) and **execute** (produce a `Reply`).

```
decide(message)
  ├─ "summary"                                → summary                       source=command
  ├─ medical / legal guardrail rule matched    → escalate                      source=guardrail
  ├─ LLM classifier, confidence ≥ 0.6          → action for the intent        source=llm
  └─ classifier error or low confidence        → keyword rules decide          source=rules_fallback

execute(decision)
  ├─ escalate     → handoff reply, reason logged
  ├─ faq          → answer from the SOP (NO_SOP_ANSWER sentinel → SOP gap)
  ├─ unanswered   → SOP gap (3rd gap → escalate)
  ├─ lead_answer  → store the answer, ask the next question
  └─ greeting / thanks / smalltalk → fixed reply (+ pending lead question)
```

Set `ROUTER_MODE=rules` to run the keyword router only. The eval uses this as its baseline.

## Project structure

```
app.py                 Flask app: /, /chat, /reset; input validation, sessions
chatbot.py             decide() / execute() router and the SOP-answering LLM call
classifier.py          LLM intent classifier (Pydantic structured output)
evals/                 Labelled routing cases, eval runner, results.md
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
GROQ_MODEL=openai/gpt-oss-120b            # optional: answering model
GROQ_CLASSIFIER_MODEL=openai/gpt-oss-20b  # optional: classifier model
CLASSIFIER_CONFIDENCE_THRESHOLD=0.6       # optional
ROUTER_MODE=llm                           # optional: llm | rules
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

The suite covers:

- escalation rules, including negation and false-positive cases
- both routers
- the 3-unanswered-questions rule
- LLM and classifier failure fallbacks, the low-confidence fallback, and guardrail precedence
- the full lead flow and summary
- session isolation between two clients
- API input validation

The LLM and the classifier are replaced with fakes, so the tests are fast and need no API key.

## Evals

```bash
python evals/run_routing_eval.py                # rules vs llm, writes evals/results.md
python evals/run_routing_eval.py --modes llm
```

[evals/routing_cases.json](evals/routing_cases.json) holds 52 labelled messages. 14 of them are hard cases written to beat keywords: paraphrases ("I want my money back"), aftercare questions with no medical keyword, below-list-price offers ("Botox for £150?"), and lead answers that start with a question word ("any time after 5 is good"). Each case is scored on what the agent actually did end to end (answered, SOP gap, escalated and why, lead answer recorded). Rate-limited calls are retried, so a 429 can't quietly turn into a fallback route.

## Known limitations / next steps

- The guardrail is deliberately strict. "Is it safe to pay by card?" escalates as medical because of the word "safe". This is the one remaining eval failure, accepted on purpose.
- The LLM router adds a classification call, so a FAQ reply takes about 3.5s (classify + answer) against about 0.3s with rules only. Next step: merge classification and answering into one call for FAQs, or stream replies.
- Sessions are stored in memory (single process, cleared on restart). Production would use Redis or a database.
- Escalations are logged but don't create tickets yet. Planned: persist handoff tickets and add an admin view.
- The SOP is a Python string. Planned: load it from per-business config (YAML/JSON).

## Author

Sujan M
