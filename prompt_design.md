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

Defined in `prompts.py`:

```
You are a customer support assistant for Bloom Aesthetics Clinic.

Rules you must follow:

1. Answer ONLY with facts stated in the SOP DATA below. Do not add, infer or assume anything.
2. If the SOP DATA does not contain the answer, reply with exactly NO_SOP_ANSWER and nothing else.
3. Never give medical advice and never negotiate prices. If asked, reply with exactly NO_SOP_ANSWER.
4. Keep answers to one or two short sentences.
5. Use a warm, professional tone suitable for a small clinic.
6. Do not ask the customer follow-up questions; the system handles that.
```

The SOP text is appended under `SOP DATA:`. The last 10 messages of the conversation are sent with it, both customer and assistant turns, so the model can resolve follow-ups like "and on Saturday?". Temperature is 0.

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

Rules live in `escalation.py`, grouped by reason:

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

Starts after the first successfully answered SOP question. Fields: name, treatment, preferred time, contact. While a question is pending:

- a non-question message is stored as the answer,
- a question is answered (or escalated) first, then the pending question is asked again,
- escalation rules still apply.

## Summary

`summary` (or the Summary button) shows a summary built from the tracked state rather than from a template: number of messages, topics asked about, lead status and fields, SOP gaps, escalation reasons, and a recommended next action (follow up on the escalation, contact the lead to book, or collect the missing lead details).

## Tone

Professional, warm, concise and non-technical. All fixed replies (greeting, fallback, handoff) are written in code so the tone is the same every time.
