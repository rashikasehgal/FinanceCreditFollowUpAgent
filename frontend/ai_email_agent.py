"""
Standalone helper for testing Groq-powered payment reminders (no Gemini).

Run from the frontend folder:
    python ai_email_agent.py

Requires GROQ_API_KEY in the environment or in a .env file next to this script.
"""
import json
import os

from dotenv import load_dotenv
from groq import Groq

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

GROQ_MODEL = "llama-3.3-70b-versatile"


def generate_email(client_name, invoice_no, amount, due_date, overdue_days, stage):
    """
    Returns a dict with 'subject' and 'body' using Groq chat completions.
    """
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Set GROQ_API_KEY in your environment or .env file.")

    if stage == "Stage 1":
        tone = "Warm, polite reminder."
    elif stage == "Stage 2":
        tone = "Polite but firm."
    elif stage == "Stage 3":
        tone = "Formal and serious."
    elif stage == "Stage 4":
        tone = "Stern final notice; mention possible escalation."
    else:
        return {
            "subject": "Manual Review Required",
            "body": "This invoice requires manual legal/finance review. No automated email sent.",
        }

    system_msg = (
        "You are a Finance Credit Controller. Output VALID JSON ONLY with keys subject and body. "
        "No markdown fences. Sign off as Finance Department."
    )
    user_msg = f"""Invoice: {invoice_no}, client {client_name}, amount ₹{amount:,.2f}, due {due_date}, {overdue_days} days overdue.
Stage: {stage}. Tone: {tone}
JSON: {{"subject": "...", "body": "..."}}"""

    client = Groq(api_key=api_key)
    completion = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.45,
        max_tokens=1024,
    )
    raw = completion.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1] if "\n" in raw else raw
        raw = raw.replace("```json", "").replace("```", "").strip()
    data = json.loads(raw)
    return {"subject": data["subject"], "body": data["body"]}


if __name__ == "__main__":
    print("Testing Groq AI Email Generator...\n")
    out = generate_email(
        client_name="Priya Sharma",
        invoice_no="INV-2026-1005",
        amount=45000.00,
        due_date="2026-05-05",
        overdue_days=7,
        stage="Stage 1",
    )
    print("SUBJECT:", out.get("subject"))
    print("BODY:\n", out.get("body"))
