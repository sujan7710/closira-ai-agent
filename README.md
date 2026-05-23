# Closira AI Customer Support Agent

AI-powered customer support workflow built using Flask, LangChain, and Groq LLM.

---

# Features

- SOP-grounded FAQ answering
- Hallucination prevention
- Lead qualification workflow
- Escalation detection
- Conversation summarization
- Modern chat UI
- Modular AI workflow architecture

---

# Technologies Used

- Python
- Flask
- LangChain
- Groq API
- HTML
- CSS
- JavaScript

---

# Project Structure

```text
closira-ai-agent/
│
├── app.py
├── chatbot.py
├── escalation.py
├── lead_qualification.py
├── memory.py
├── prompts.py
├── sop_data.py
├── summary.py
├── tools.py
│
├── README.md
├── prompt_design.md
├── requirements.txt
├── .gitignore
│
├── templates/
│   └── index.html
│
├── static/
│   └── style.css
│
└── test_transcripts/
    ├── in_scope.txt
    ├── out_of_scope.txt
    ├── escalation.txt
    ├── qualification_case.txt
    └── summary_case.txt
```

---

# Setup Instructions

## 1. Clone Repository

```bash
git clone https://github.com/sujan7710/closira-ai-agent.git
```

---

## 2. Create Virtual Environment

```bash
python -m venv venv
```

---

## 3. Activate Virtual Environment

### Windows

```bash
venv\Scripts\activate
```

---

## 4. Install Dependencies

```bash
pip install -r requirements.txt
```

---

## 5. Configure Environment Variables

Create a `.env` file in the project root:

```env
GROQ_API_KEY=your_api_key
```

---

## 6. Run Application

```bash
python app.py
```

The application will start on:

```text
http://127.0.0.1:5000
```

---

# Workflow Stages

The AI workflow consists of four stages:

1. FAQ Answering
2. Lead Qualification
3. Escalation Detection
4. Conversation Summary

---

# SOP Information

Business: Bloom Aesthetics Clinic

Services:
- Botox (from £200)
- Fillers (from £250)
- Free consultations

Booking:
- Via WhatsApp or website

Business Hours:
- Mon–Sat, 9 am–7 pm

Escalation Conditions:
- Complaint
- Medical question
- Pricing negotiation
- Out-of-scope questions

---

# Test Scenarios

The system supports:

- In-SOP customer queries
- Out-of-scope escalation
- Lead qualification
- Escalation handling
- Conversation summaries

Sample transcripts are included in the `test_transcripts/` folder.

---

# Hallucination Prevention

The AI is restricted to answering only from the provided SOP data.

Safety mechanisms include:
- SOP keyword filtering
- Strict system prompts
- Out-of-scope escalation
- Controlled response generation

---

# Known Limitations

- Uses keyword-based SOP relevance detection
- No persistent database storage
- Single-session memory only

Note:
Groq API was used as an OpenAI-compatible LLM provider during development due to OpenAI quota limitations. The workflow architecture remains compatible with OpenAI or Anthropic APIs.

---

# Author

Sujan M
