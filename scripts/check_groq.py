"""Smoke test: confirm the Groq API key in .env works. Run: python scripts/check_groq.py"""

import os
import sys

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

api_key = os.getenv("GROQ_API_KEY")
if not api_key:
    sys.exit("GROQ_API_KEY is not set (add it to .env)")

client = Groq(api_key=api_key)
response = client.chat.completions.create(
    model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
    messages=[{"role": "user", "content": "Say hello"}],
)
print("Groq connection OK:", response.choices[0].message.content)
