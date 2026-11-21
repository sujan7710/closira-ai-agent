# Lead extraction eval

Cases: 20 (both businesses). A case passes only if every expected field is stored correctly after validation and no other field is filled.

| Mode | Cases correct | Multi-field cases | Correctly left empty |
|---|---|---|---|
| rules | **11/20 (55%)** | 0/5 | 2/2 |
| llm | **18/20 (90%)** | 5/5 | 1/2 |

## rules: failures

| Message | Expected | Stored |
|---|---|---|
| It's Priya | name=Priya | name=It's Priya |
| my name is Tom and I'd like botox | name=Tom, treatment=Botox | name=my name is Tom and I'd like botox |
| probably the lip fillers... actually, my name is Priya | name=Priya, treatment=Fillers | name=probably the lip fillers... actually, my name is Priya |
| Jo Brown, fillers please, Saturday at 2 | name=Jo Brown, treatment=Fillers, preferred_time=saturday… | name=Jo Brown, fillers please, Saturday at 2 |
| any weekday after 5pm, my number is 07700 900123 | preferred_time=5…, contact=07700900123 | (nothing) |
| Ahmed Khan here | name=Ahmed Khan | name=Ahmed Khan here |
| my teeth need a good clean | treatment=Hygienist clean | (nothing) |
| I want them whiter for my wedding | treatment=Teeth whitening | (nothing) |
| I've been a patient for years, call me on 020 7946 0999 | visited_before=Yes, contact=02079460999 | visited_before=Yes |

## llm: failures

| Message | Expected | Stored |
|---|---|---|
| I'd like to chat to someone first, the free one | treatment=Free consultation | (nothing) |
| something for my forehead wrinkles | (nothing) | treatment=Botox |

## Notes

- Extractor model: `openai/gpt-oss-20b` (default). `openai/gpt-oss-120b` scored the same 18/20, so the faster model is kept.
- The first prompt ("fill a field ONLY if clearly stated", message sent alone) scored 11/20 with the LLM, the same as raw answers. The model returned all-null for plain replies like "Saturday morning works". Sending the exchange as "Assistant asked / Customer replied" and asking for every stated field fixed it.
- Remaining misses: "chat to someone first" is ambiguous with a request for a human, and "forehead wrinkles → Botox" is an inference the agent should not make. A treatment suggestion is advice, so a stricter option-matching rule is a possible next step.
