from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage
from dotenv import load_dotenv
import os

from prompts import SYSTEM_PROMPT
from sop_data import SOP, SOP_KEYWORDS
from escalation import check_escalation
from lead_qualification import questions as lead_questions
from summary import generate_summary

load_dotenv()

llm = ChatGroq(
    groq_api_key=os.getenv("GROQ_API_KEY"),
    model_name="llama-3.3-70b-versatile"
)

conversation_history = []

lead_answers = []

current_question = 0

qualification_started = False


def is_question(text):

    question_words = [
        "what",
        "how",
        "do",
        "does",
        "can",
        "is",
        "are",
        "where",
        "when",
        "why"
    ]

    text = text.lower().strip()

    if "?" in text:
        return True

    return any(
        text.startswith(word)
        for word in question_words
    )


def get_response(user_input):

    global current_question
    global qualification_started

    user_lower = user_input.lower()

    # -----------------------------------
    # Generate Conversation Summary
    # -----------------------------------

    if user_lower == "summary":

        return generate_summary(
            conversation_history,
            lead_answers
        )

    # -----------------------------------
    # Escalation Detection
    # -----------------------------------

    escalation, reason = check_escalation(user_input)

    if escalation:
        return f"Escalating to human agent.\nReason: {reason}"

    # -----------------------------------
    # SOP Relevance Detection
    # -----------------------------------

    relevant = any(
        keyword in user_lower
        for keyword in SOP_KEYWORDS
    )

    # -----------------------------------
    # Out-of-Scope Detection
    # -----------------------------------

    if is_question(user_input) and not relevant:

        return (
            "I do not have that information in the SOP. "
            "I will escalate this to a human agent."
        )

    # -----------------------------------
    # FAQ Answering
    # -----------------------------------

    if relevant:

        conversation_history.append(
            HumanMessage(content=user_input)
        )

        messages = [
            SystemMessage(
                content=SYSTEM_PROMPT + "\n\nSOP DATA:\n" + SOP
            )
        ] + conversation_history

        response = llm.invoke(messages)

        ai_response = response.content

        # Start qualification only once
        if not qualification_started:

            qualification_started = True

            ai_response += (
                f"\n\n{lead_questions[current_question]}"
            )

            current_question += 1

        return ai_response

    # -----------------------------------
    # Lead Qualification Flow
    # -----------------------------------

    if qualification_started:

        lead_answers.append(user_input)

        if current_question < len(lead_questions):

            question = lead_questions[current_question]

            current_question += 1

            return question

        return (
            "Thank you for the information. "
            "Lead qualification completed successfully.\n\n"
            "Type 'summary' to generate conversation summary."
        )

    # -----------------------------------
    # Fallback
    # -----------------------------------

    return (
        "I do not have that information in the SOP. "
        "I will escalate this to a human agent."
    )