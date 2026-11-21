# Prompt and Workflow Design

## Intent classifier (v2 router)

`classifier.py` asks the model for a typed `Classification`:

```python
class Classification(BaseModel):
    intent: Literal["greeting", "thanks", "smalltalk", "faq", "out_of_scope", "lead_answer",
                    "complaint", "human_request", "legal", "medical", "price_negotiation"]
    confidence: float  # 0..1
    topics: list[Literal[<SOP topics>]]
```

It uses LangChain `with_structured_output(..., method="json_schema")`, so Groq enforces the schema and the result is validated by Pydantic. No string parsing is needed.

**What the prompt includes:** the full SOP, so the model can tell `faq` from `out_of_scope`. A one-line definition of each intent with the tricky boundaries spelled out: asking a price is `faq`, asking for a lower price is `price_negotiation`, aftercare and recovery count as `medical`, negated statements are not complaints. A priority order for messages that fit more than one intent (medical > legal > complaint > human_request > price_negotiation). And an instruction to report confidence honestly.

**What it sees per message:** the last 4 messages, the pending lead question (if any) and the latest message. The pending question is what lets "Botox" or "any time after 5 is good" be read as a lead answer.

**How the router uses it:**

| Condition | Who decides |
|---|---|
| Medical/legal keyword rule matches | Guardrail (escalates; the classifier is not called) |
| Classifier confidence ≥ 0.6 | Classifier |
| Confidence < 0.6, or the classifier errored | Keyword rules (`rules_fallback`) |

The guardrail is asymmetric on purpose: in a clinic, missing a medical question costs far more than a false alarm.

**Model choice:** `gpt-oss-20b` matched `gpt-oss-120b` on the eval (98%) with about 0.9s less latency, so the smaller model classifies and the larger one writes answers. See `evals/results.md`.

## Answering system prompt

Built per business by `build_answer_prompt()` in `prompts.py` (business name and SOP come from the YAML config):

```
You are a customer support assistant for {business.name}.

Rules you must follow:

1. Answer ONLY with facts stated in the SOP DATA below. Do not add, infer or assume anything.
2. If the SOP DATA does not contain the answer, reply with exactly NO_SOP_ANSWER and nothing else.
3. Never give medical or clinical advice and never negotiate prices. If asked, reply with exactly NO_SOP_ANSWER.
4. Keep answers to one or two short sentences.
5. Use a warm, professional tone suitable for a small business.
6. Do not ask the customer follow-up questions; the system handles that.
```

The business's SOP text is appended under `SOP DATA:`. The last 10 messages of the conversation are sent with it, both customer and assistant turns, so the model can resolve follow-ups like "and on Saturday?". Temperature is 0.

### Why a sentinel token

The original prompt asked the model to reply with an exact fallback sentence. That's fragile: the model paraphrases it, and the code can't reliably tell that the question went unanswered. A single token is easy for the model to produce verbatim and easy for the code to detect. The code then:

- shows a fixed, human-written fallback reply,
- records the question as an **SOP gap** (shown in the summary),
- escalates once there are more than 2 gaps (an SOP rule).

The customer-facing wording is fixed by the code, not chosen by the model.

## Preventing hallucinations (layered)

1. **Escalations never reach the answering model.** Medical questions, pricing negotiation, complaints, legal threats and requests for a human are routed to a human by the classifier, with keyword guardrails for medical and legal.
2. **Only `faq` messages are answered.** Out-of-scope questions are logged as gaps without an answering call.
3. **SOP-only prompt plus the sentinel.** If the topic filter over-matches (e.g. "laser hair removal *services*"), the model returns `NO_SOP_ANSWER` instead of guessing. This has been checked against the real model; see `test_transcripts/out_of_scope.txt`.
4. **Temperature 0** and short answers.
5. **Fail closed.** If the LLM call errors or times out, the customer gets a handoff message and the error is recorded as an escalation. They never see a stack trace or an empty reply.

## Escalation

`escalation.py` holds a library of rule categories. Each business's YAML chooses which are `enabled`, which are `guardrails` (always enforced, even over the classifier), adds `extra_patterns` (e.g. toothache and abscess for the dental practice), and can define `custom` categories with their own label and reply (the dental practice's `insurance`). Custom categories are rules-only, so they are always treated as guardrails.

| Reason | Example triggers |
|---|---|
| Complaint or frustration | angry, terrible, refund, unhappy, bad service |
| Customer requested a human | manager, speak to a person, human agent |
| Legal threat | lawsuit, lawyer, sue the clinic |
| Medical question | pregnancy, side effects, allergy, safe, swelling |
| Pricing negotiation | discount, cheaper, price match, too expensive |
| More than 2 unanswered questions | counted by the router |
| Assistant error | LLM unavailable or timed out |

Patterns match on word boundaries, so "Sue" as a name or "offer" in "do you offer fillers" don't trigger. A trigger is ignored if a negation ("not", "no", "never", "don't", ...) appears within the three words before it. Each escalation is logged as `ESCALATION session=<id> reason=<reason>`, stored on the conversation, and returned to the UI as a badge.

## Lead qualification

Starts after the first successfully answered SOP question. The fields, questions and types (`text`, `phone`, `choice` with options) come from the business config. The pending field is always the first one still missing.

**Extraction (LLM) and validation (code).** When the customer answers, `extractor.py` asks the LLM for a per-business Pydantic model built from the lead fields. Choice fields become `Literal[...]` of the options, so the model can only pick a valid option or null. The prompt:

```
You extract booking details for {name} from a customer's reply.

Return a value for every field the customer states in their reply, especially the field the
assistant asked about. Use null only for fields the customer did not mention. Never invent values.
Keep values short: a name, not a sentence; the day/time as they said it.
For choice fields, pick the option that best matches what the customer said, or null if none fits.
```

The input is sent as `Assistant asked: … / Customer replied: …`. A first version that said "fill a field ONLY if clearly stated" and sent the message alone made the model return all-null for plain answers. It scored 11/20, no better than storing the raw reply. The current version scores 18/20 (`evals/extraction_results.md`).

Every value, from the LLM or raw, then goes through code validators: phone numbers are extracted and normalised (7 to 15 digits), and choices are mapped to an option (exact, yes/no phrasing, or best word overlap). If the pending field is still missing or invalid, the customer gets a specific retry prompt instead of the next question. If extraction fails, or in rules mode, the raw reply is validated for the pending field. For phone and choice fields the raw reply is also tried when the LLM missed it, because their validators are strict.

While a question is pending, a question from the customer is answered (or escalated) first, then the pending question is asked again. Escalation rules still apply.

## Staff inbox and persistence

`storage.py` (SQLite) is called by the web layer after every reply, so the agent stays storage-free and a database error never breaks the chat.

- **Tickets:** one open ticket per conversation. Later escalations add a reason, and the transcript and lead keep updating while the ticket is open.
- **Leads:** upserted per conversation, marked complete when every field is filled.
- **SOP gaps:** every unanswered question is stored with normalised text, and `/admin` shows them ranked by frequency.

## Summary

`summary` (or the Summary button) shows a summary built from the tracked state rather than from a template: number of messages, topics asked about, lead status and fields, SOP gaps, escalation reasons, and a recommended next action (follow up on the escalation, contact the lead to book, or collect the missing lead details).

## Tone

Professional, warm, concise and non-technical. All fixed replies (greeting, fallback, handoff) come from each business's config (with code defaults), not from the model, so the wording is consistent and on-brand.
