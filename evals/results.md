# Routing eval results

Cases: 52 · model: `openai/gpt-oss-120b` · classifier: `openai/gpt-oss-120b` (see comparison below) · confidence threshold: 0.6

| Router | Accuracy | Escalation recall | False escalations | Hard cases (no keyword) | Avg latency |
|---|---|---|---|---|---|
| rules | **39/52 (75%)** | 7/16 | 1 | 1/14 | 0.24s |
| llm | **51/52 (98%)** | 16/16 | 1 | 13/14 | 4.33s |

## rules: failures

Decision sources: rules=47, guardrail=5

| Message | Expected | Got | Source | Note |
|---|---|---|---|---|
| Can I come in at 8pm? | answered | sop_gap | rules | no SOP keyword |
| Do I need to give notice if I can't make it? | answered | sop_gap | rules | cancellation, no keyword |
| I've been waiting three days for a reply, this is ridiculous | escalated:complaint | smalltalk | rules | no keyword |
| I want my money back | escalated:complaint | smalltalk | rules | paraphrased refund |
| Your receptionist was really rude to me | escalated:complaint | smalltalk | rules | no keyword |
| Is there someone at the clinic I can call instead of a bot? | escalated:human_request | sop_gap | rules | paraphrase |
| Will Botox interact with my antidepressants? | escalated:medical | sop_gap | rules | no keyword |
| How long is the recovery after fillers? | escalated:medical | sop_gap | rules | aftercare, no keyword |
| Can I go to the gym straight after Botox? | escalated:medical | sop_gap | rules | aftercare, no keyword |
| Can you do Botox for £150? | escalated:price_negotiation | sop_gap | rules | no keyword |
| Any chance of a better rate if I book both treatments? | escalated:price_negotiation | sop_gap | rules | no keyword |
| Is it safe to pay by card on your website? | sop_gap | escalated:medical | guardrail | known guardrail false positive ('safe') |
| any time after 5 is good | lead_answer | sop_gap | rules | starts with a question word |

## llm: failures

Decision sources: llm=47, guardrail=5

| Message | Expected | Got | Source | Note |
|---|---|---|---|---|
| Is it safe to pay by card on your website? | sop_gap | escalated:medical | guardrail | known guardrail false positive ('safe') |

## Classifier model comparison

Same 52 cases, LLM router, answering model `openai/gpt-oss-120b` in both runs.

| Classifier model | Accuracy | Escalation recall | Avg latency (classify + answer) |
|---|---|---|---|
| `openai/gpt-oss-120b` | 51/52 (98%) | 16/16 | 4.33s |
| `openai/gpt-oss-20b` | 51/52 (98%) | 16/16 | 3.45s |

The 20b model matched the 120b model's accuracy with about 0.9s less latency, so it is the default classifier (`GROQ_CLASSIFIER_MODEL`).
