SOP = """
Business: Bloom Aesthetics Clinic

Hours:
Mon–Sat, 9 am–7 pm

Services:
- Botox (from £200)
- Fillers (from £250)
- Free consultations

Booking:
Via WhatsApp or website

Cancellation Policy:
24hr cancellation required

Escalate if:
- Complaint
- Medical question
- Pricing negotiation
- More than 2 unanswered questions
"""

# Topic -> trigger patterns (regex, matched on word boundaries, case-insensitive).
# Used for a cheap pre-filter and for summarising what the customer asked about.
# Over-matching is safe: the LLM is instructed to return a sentinel when the SOP
# does not actually contain the answer, so a false keyword hit cannot cause a
# hallucinated reply.
SOP_TOPICS = {
    "botox": [r"botox"],
    "fillers": [r"fillers?", r"dermal"],
    "consultations": [r"consult(ation)?s?", r"free"],
    "booking": [r"book(ing|ed)?", r"appointments?", r"whatsapp", r"website", r"schedule"],
    "opening hours": [
        r"hours?", r"open(ing)?", r"clos(e|ed|ing)", r"timings?",
        r"(mon|tues|wednes|thurs|fri|satur|sun)days?", r"weekends?", r"today", r"tomorrow",
    ],
    "cancellation": [r"cancel(l?ation|l?ed|l?ing)?s?", r"reschedul(e|ing)"],
    "pricing": [r"prices?", r"pricing", r"costs?", r"how much", r"fees?", r"£"],
    "services": [r"services?", r"treatments?", r"offer"],
}
