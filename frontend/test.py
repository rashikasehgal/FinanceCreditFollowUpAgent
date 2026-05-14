"""
Quick sanity check for Groq (optional).

Set GROQ_API_KEY in your environment or create frontend/.env before running:
    python test.py
"""
import os

from dotenv import load_dotenv
from groq import Groq

BASE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE, ".env"))

key = os.environ.get("GROQ_API_KEY", "").strip()
if not key:
    print("Missing GROQ_API_KEY — add it to .env or your shell environment.")
    raise SystemExit(1)

client = Groq(api_key=key)
resp = client.chat.completions.create(
    model="llama-3.3-70b-versatile",
    messages=[{"role": "user", "content": "Write one sentence: what is accounts receivable?"}],
    max_tokens=80,
)
print(resp.choices[0].message.content)
