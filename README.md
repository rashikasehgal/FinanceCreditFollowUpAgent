This README.md file should be placed in the root GitHub repository folder.

---

# AI-Powered Finance Credit Follow-Up Agent

[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io/)
[![SQLite](https://img.shields.io/badge/SQLite-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org/)

A Streamlit application that automates **overdue invoice tracking**, **escalation workflows**, **AI-assisted follow-up email drafting**, **optional Gmail SMTP delivery**, **SQLite persistence**, and **audit logging** for accounts receivable-style operations.

---

## Tech Stack

| Category | Technology |
|----------|------------|
| Language | Python |
| UI | Streamlit |
| Database | SQLite3 (`sqlite3`) |
| AI | Groq API (Llama 3.3) |
| Email | SMTP (Gmail, `smtplib`) |
| Data | Pandas |
| Visualization | Plotly |

---

## Features

- CSV invoice upload with de-duplication by invoice number
- Overdue day calculation and escalation stage assignment
- Risk level classification
- AI-generated payment reminder copy (with template fallback)
- Optional real email sending via SMTP
- Dry-run email simulation (no SMTP, no database changes for the simulation path)
- SQLite persistence for invoices and send status
- Append-style audit logging for traceability
- Manual escalation override with reasons
- Export of generated email payloads to CSV and JSON

---

## Workflow

```
CSV Upload
    → SQLite Storage
    → Overdue Calculation
    → Escalation Engine
    → AI Email Generation
    → SMTP Sending (optional)
    → Audit Logging
```

---

## Escalation Logic

| Stage | Days Overdue | Tone (summary) |
|-------|----------------|----------------|
| Not Overdue | 0 | No collection action |
| Stage 1 | 1–7 | Friendly reminder |
| Stage 2 | 8–14 | Polite, firm follow-up |
| Stage 3 | 15–21 | Formal urgency |
| Stage 4 | 22–30 | Final notice before escalation |
| Escalate | 31+ | Manual / legal review path |

---

## Database Schema

**`invoices`**  
Stores one row per invoice: identifiers, client and contact fields, monetary amount, due date, computed overdue metrics, escalation stage, risk label, and email send status.

**`audit_logs`**  
Stores timestamped events (for example generation, SMTP send, manual overrides) with invoice reference, action label, stage or status transitions where applicable, and a short reason or detail field.

---

## Installation

From the repository root:

```bash
git clone <YOUR_REPOSITORY_URL>
cd <REPOSITORY_FOLDER>
pip install -r frontend/requirements.txt
streamlit run frontend/app.py
```

Then open the local URL shown in the terminal (typically `http://localhost:8501`).

---

## Environment Variables

Create a file named **`.env`** in the **`frontend/`** directory (next to `app.py`) and add:

| Variable | Purpose |
|----------|---------|
| `GROQ_API_KEY` | Authenticates requests to the Groq API for AI-generated email text |

If the key is omitted, the application continues using the built-in template generator without surfacing a configuration warning in the UI.

---

## SMTP Setup (Gmail)

Real sending uses **Gmail SMTP** on port **587** with **STARTTLS**. In the app sidebar, supply the sender Gmail address and a **Google App Password** (not your normal Gmail password). App Passwords require **2-Step Verification** on the Google account. Use the in-app fields only on trusted machines; never commit credentials to the repository.

---

## Future Improvements

- Scheduled batch runs and reminders  
- ERP or accounting system integration  
- Payment gateway linkage for status sync  
- User authentication and role-based access control  

---

## Author

This repository is presented as a **portfolio-style** full-stack Python project: it combines a practical finance operations workflow with clear separation of UI, persistence, external AI services, and optional email delivery, suitable for discussion in interviews or internship reviews.
