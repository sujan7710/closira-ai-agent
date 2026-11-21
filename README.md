# Closira AI Customer Support Agent

[![CI](https://github.com/sujan7710/closira-ai-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/sujan7710/closira-ai-agent/actions/workflows/ci.yml)

A multi-business AI support agent for small businesses. Each business is a YAML file. The agent answers FAQs strictly from that business's SOP, qualifies leads, hands off to a human when the SOP says it must, and gives staff an inbox of handoffs, leads and unanswered questions.

Two demo businesses are included: **Bloom Aesthetics Clinic** and **Brightside Dental Studio**.

Built with Flask, LangChain, Groq (`gpt-oss-120b` for answers, `gpt-oss-20b` for classification and extraction) and SQLite.

## Results

Measured end to end against the real model ([evals/](evals/)):

| Eval | Keyword rules / raw answers | LLM |
|---|---|---|
| Routing, 52 cases ([results](evals/results.md)) | 75% | **98%** |
| Escalations caught | 7/16 | **16/16** |
| Lead extraction, 20 cases ([results](evals/extraction_results.md)) | 55% | **90%** |
| Multi-field lead replies ("Jo Brown, fillers, Saturday at 2") | 0/5 | **5/5** |

## Features

**Multi-business**
- **One YAML file per business** ([businesses/](businesses/)). It holds the SOP, topic keywords, which escalation categories are on, guardrails, custom categories, customer-facing replies, lead fields and the theme colour. Adding a business needs no code changes.
- **Validated on load.** Pydantic rejects broken configs at startup: a choice field with no options, a guardrail that isn't enabled, an invalid theme colour.
- **Custom escalation categories.** The dental practice adds an `insurance` category with its own patterns and reply, plus dental medical keywords (toothache, bleeding, abscess).
- `/b/<business>` serves a branded chat page for each business, and sessions, tickets and leads are kept separate per business.

**Staff inbox (`/admin`)**
- **Handoff tickets.** Every escalation opens a ticket with its reasons, the lead details and the full transcript. There is one ticket per conversation: later escalations add a reason, and the transcript keeps updating while the ticket is open. Staff close tickets with a resolution note.
- **Leads.** Partial and complete leads, with labelled fields.
- **SOP gap report.** Questions the agent couldn't answer, grouped and ranked by how often they were asked. It tells the business what to add to its SOP.
- **Security.** HTTP Basic auth via `ADMIN_PASSWORD`. Without a password the inbox only answers on localhost. The close form is CSRF-protected, redirects can't leave the site, and customer text is HTML-escaped.

**Agent**
- **LLM intent classifier.** Each message is sorted into one of 11 intents with a confidence score, as a typed Pydantic model returned through Groq's JSON-schema structured output. It sees recent context and the pending lead question.
- **Confidence threshold with a rule-based fallback.** If the classifier errors or its confidence is below 0.6, the keyword router decides instead.
- **Guardrails.** Each business's guardrail rules (Bloom: medical and legal; dental: those plus insurance) always win, even over a confident classifier.
- **LLM lead extraction with deterministic validation.** The LLM pulls every field the customer states ("probably the lip fillers… actually my name is Priya" gives name = Priya and treatment = Fillers). Code then validates each value: phone numbers are normalised, and choices must map to a configured option. An invalid value gets a specific retry prompt ("Please choose Botox, Fillers or Free consultation").
- **SOP-grounded answers.** When the SOP doesn't cover a question, the model must return a sentinel token (`NO_SOP_ANSWER`). The code shows a fixed reply, records an SOP gap, and escalates on the third gap.
- **Routing trace.** Every reply carries what happened, who decided (`llm`, `guardrail`, `rules_fallback`) and the classifier's confidence. It's shown in the UI and the API response and is logged.
- **Structured summary**, **per-user sessions**, **XSS-safe UI**, and logging of every escalation, gap and lead field.

## How a message is handled

```
decide(message)
  ├─ "summary"                                → summary                       source=command
  ├─ business guardrail rule matched           → escalate                      source=guardrail
  ├─ LLM classifier, confidence ≥ 0.6          → action for the intent        source=llm
  └─ classifier error or low confidence        → keyword rules decide          source=rules_fallback

execute(decision)
  ├─ escalate     → handoff reply from config, reason logged
  ├─ faq          → answer from the SOP (NO_SOP_ANSWER sentinel → SOP gap)
  ├─ unanswered   → SOP gap (3rd gap → escalate)
  ├─ lead_answer  → LLM extraction → validators → next missing field, or a retry prompt
  └─ greeting / thanks / smalltalk → reply from config (+ pending lead question)

web layer → storage.record_turn()  → tickets / leads / sop_gaps (SQLite)
```

The agent itself never touches the database. The web layer saves each turn, so the agent stays easy to test, and a database failure never breaks the customer's chat.

`ROUTER_MODE=rules` runs without the classifier and extractor. The evals use it as their baseline.

## Project structure

```
app.py                 Flask: chat pages per business, /chat, /reset, /admin inbox, /healthz
ratelimit.py           Per-client and daily rate limits for the public demo
Dockerfile             Production image (gunicorn, non-root, health check)
docker-compose.yml     Run the image locally with a persistent volume
render.yaml            Render Blueprint for a one-click live demo
.github/workflows/     CI: tests, then Docker build and container smoke test
business.py            Business config models (Pydantic) and loader
businesses/*.yaml      One file per business
chatbot.py             decide() / execute() router and the SOP-answering LLM call
classifier.py          LLM intent classifier (topics typed per business)
extractor.py           LLM lead extraction + phone/choice validators
escalation.py          Escalation rule library with negation handling
storage.py             SQLite: tickets, leads, SOP gaps, gap report
conversation.py        ConversationState + in-memory SessionStore
summary.py             Structured summary
prompts.py             Answering prompt and NO_SOP_ANSWER sentinel
templates/, static/    Chat UI and staff inbox
tests/                 pytest suite (LLM faked, runs offline)
evals/                 Routing and extraction evals with results
test_transcripts/      Sample conversations recorded against the real model
scripts/check_groq.py  Checks that your Groq API key works
```

## Setup

```bash
git clone https://github.com/sujan7710/closira-ai-agent.git
cd closira-ai-agent
python -m venv venv
venv\Scripts\activate          # Windows  (source venv/bin/activate on macOS/Linux)
pip install -r requirements-dev.txt
```

Create `.env`:

```
GROQ_API_KEY=your_api_key
FLASK_SECRET_KEY=any-long-random-string   # recommended; random per process if unset
ADMIN_PASSWORD=choose-one                 # required for /admin outside localhost
DEFAULT_BUSINESS=bloom                    # optional
CLOSIRA_DB=closira.db                     # optional: SQLite file
GROQ_MODEL=openai/gpt-oss-120b            # optional: answering model
GROQ_CLASSIFIER_MODEL=openai/gpt-oss-20b  # optional
GROQ_EXTRACTOR_MODEL=openai/gpt-oss-20b   # optional (defaults to the classifier model)
CLASSIFIER_CONFIDENCE_THRESHOLD=0.6       # optional
ROUTER_MODE=llm                           # optional: llm | rules
CHAT_RATE_LIMIT=20/60                     # optional: messages per client per N seconds (0 = off)
CHAT_DAILY_LIMIT=0                        # optional: total messages per day across all users (0 = off)
APP_ENV=development                       # production: enforce config, secure cookies, proxy headers
TRUST_PROXY=1                             # production only: trust X-Forwarded-For (set 0 without a proxy)
```

Run:

```bash
python app.py        # chat: http://127.0.0.1:5000   inbox: http://127.0.0.1:5000/admin
```

### Adding a business

Copy `businesses/bloom.yaml`, change the `id`, SOP, topics, replies and lead fields, and restart. It appears at `/b/<id>`, in the business switcher and in the inbox filters.

## Deployment

**Production mode** (`APP_ENV=production`, set by the Docker image):

- The app refuses to start without `FLASK_SECRET_KEY` and `GROQ_API_KEY`.
- The staff inbox is disabled until `ADMIN_PASSWORD` is set. There is no localhost exemption, because behind a proxy every request can look local.
- Session cookies are `Secure`.
- `X-Forwarded-For` is trusted for one hop, so the rate limiter sees real client IPs. Set `TRUST_PROXY=0` when nothing sits in front of the app, otherwise clients could spoof the header.
- `/chat` is rate-limited per client (`CHAT_RATE_LIMIT`), with an optional daily cap (`CHAT_DAILY_LIMIT`) so a public demo can't use up the Groq quota.

The image runs **one gunicorn worker with 8 threads**. That's deliberate: chat sessions and the rate limiter live in memory, so several worker processes would each have their own copy. LLM calls are I/O-bound, so threads give the concurrency. Scaling out means moving sessions and limits to Redis.

### Docker

```bash
docker compose up --build      # http://localhost:8000, reads .env, SQLite kept in a volume
```

### Live demo on Render (free)

1. Push to GitHub, then go to [Render](https://render.com) → **New → Blueprint** and pick this repo. It reads [`render.yaml`](render.yaml).
2. Enter `GROQ_API_KEY` and `ADMIN_PASSWORD` when prompted. `FLASK_SECRET_KEY` is generated for you.
3. Render builds the Dockerfile, checks `/healthz`, and redeploys on every push to `main`.

Free instances sleep when idle (the first request takes about a minute) and have no persistent disk, so the SQLite inbox resets on each deploy. Add a disk at `/data` on a paid plan to keep it.

### CI

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on every push and PR:

1. Validates the business configs and runs the test suite offline.
2. Builds the Docker image and starts it.
3. Checks that `/healthz` and a chat page respond, and that `/admin` returns 401.

## Tests

```bash
python -m pytest -q
```

There are 87 tests covering:

- routing in both modes and the fallbacks
- guardrails, including custom business guardrails
- config validation
- phone and choice validators
- multi-field extraction and invalid-value retry prompts
- ticket deduplication and transcript updates
- the gap report, and keeping businesses separate
- inbox auth (localhost-only and password), CSRF, open-redirect and HTML escaping
- production mode: required config, inbox disabled without a password
- rate limiting, and proxy-header trust (spoofed `X-Forwarded-For` is ignored when `TRUST_PROXY=0`)

A `conftest.py` fixture removes the API key and the cached model clients for every test, so no test can reach the network.

## Evals

```bash
python evals/run_routing_eval.py       # rules vs llm routing → evals/results.md
python evals/run_extraction_eval.py    # raw vs LLM lead extraction → evals/extraction_results.md
```

**Routing** uses 52 labelled messages, 14 of them written to beat keywords: paraphrases, aftercare questions with no medical keyword, below-list-price offers, and lead answers that start with a question word.

**Extraction** uses 20 lead replies across both businesses. A case passes only if every expected field is stored correctly after validation and nothing else is filled in.

Rate-limited calls are retried in both evals, so a 429 can't quietly turn into a fallback result.

## Known limitations / next steps

- The guardrail is deliberately strict. "Is it safe to pay by card?" escalates as medical because of the word "safe".
- A FAQ reply takes about 3s (classify, then answer). Next: one combined call, or streaming.
- Lead extraction is 90%. It sometimes infers a treatment that wasn't requested ("forehead wrinkles → Botox").
- The gap report groups exact (normalised) wording. Next: cluster similar questions with embeddings.
- Staff can resolve tickets but can't reply into the customer's chat yet.
- Chat sessions and rate limits are kept in memory (one process), and SQLite is single-node. Scaling out would use Redis and Postgres.

Note: Groq is used as the LLM provider. The workflow is provider-agnostic: the LangChain chat models can be swapped for OpenAI or Anthropic.

## Author

Sujan M
