# Closira AI Customer Support Agent

AI-powered customer support workflow built using Flask, LangChain, and Groq LLM.

## Features

- SOP-grounded FAQ answering
- Hallucination prevention
- Lead qualification workflow
- Escalation detection
- Conversation summarization
- Modern chat UI

---

# Technologies Used

- Python
- Flask
- LangChain
- Groq API
- HTML/CSS/JavaScript

---

# Project Structure

closira-ai-agent/

├── app.py
├── chatbot.py
├── sop_data.py
├── escalation.py
├── lead_qualification.py
├── summary.py
├── prompts.py
├── prompt_design.md
├── README.md
├── requirements.txt
├── templates/
├── static/
└── test_transcripts/

---

# Setup Instructions

## 1. Clone Repository

git clone <your_repo_link>

## 2. Create Virtual Environment

python -m venv venv

## 3. Activate Virtual Environment

Windows:
venv\Scripts\activate

## 4. Install Dependencies

pip install -r requirements.txt

## 5. Configure Environment Variables

Create `.env` file:

GROQ_API_KEY=your_api_key

## 6. Run Application

python app.py

---

# Test Scenarios

The system supports:

- In-SOP customer queries
- Out-of-scope escalation
- Lead qualification
- Escalation handling
- Conversation summaries

---

# Known Limitations

- Uses keyword-based SOP relevance detection
- No persistent database storage
- Single-session memory only
- Note:Groq API was used as an OpenAI-compatible LLM provider during development due to OpenAI quota    limitations. The workflow architecture remains fully compatible with OpenAI or Anthropic APIs.

---

# Author

Sujan M