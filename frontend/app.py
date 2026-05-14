import json
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import streamlit as st
import pandas as pd
from datetime import datetime
import random
import plotly.express as px
import sqlite3
from dotenv import load_dotenv
from groq import Groq

st.set_page_config(page_title="Credit Follow-Up Dashboard", page_icon="💰", layout="wide")

# =============================================================================
# SQLITE SETUP (place this block near the top of app.py, right after imports)
# =============================================================================
# This path puts finance_agent.db in the same folder as app.py so it is easy
# to find. If you prefer the file in the folder where you run Streamlit from,
# you can change DB_PATH to simply "finance_agent.db".
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "finance_agent.db")

# =============================================================================
# Groq API setup (python-dotenv + GROQ_API_KEY)
# =============================================================================
# load_dotenv() reads .env next to this script and puts variables into os.environ.
# - encoding="utf-8-sig": avoids a hidden BOM (Notepad) breaking the variable name on line 1.
# - override=True: if Windows already has GROQ_API_KEY set (even empty), .env still wins.
load_dotenv(os.path.join(BASE_DIR, ".env"), encoding="utf-8-sig", override=True)

# Groq model id (see Groq Cloud docs). We use Llama 3.3 70B for strong writing quality.
GROQ_MODEL = "llama-3.3-70b-versatile"


def init_db():
    """
    Creates finance_agent.db (if missing) and creates the two tables.
    Streamlit reruns the script often, so we use CREATE TABLE IF NOT EXISTS.
    Safe to call on every app start.
    """
    # connect() opens the file or creates it automatically
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Table A: one row per invoice. invoice_no is the PRIMARY KEY so SQLite
    # will never allow two rows with the same invoice_no.
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS invoices (
            invoice_no TEXT PRIMARY KEY,
            client_name TEXT,
            amount REAL,
            due_date TEXT,
            email TEXT,
            overdue_days INTEGER,
            stage TEXT,
            risk_level TEXT,
            send_status TEXT
        )
        """
    )

    # Table B: append-only style log of important actions
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            invoice_no TEXT,
            action TEXT,
            old_stage TEXT,
            new_stage TEXT,
            reason TEXT
        )
        """
    )

    conn.commit()
    conn.close()


# Run once every time the app starts (and on every Streamlit rerun)
init_db()


# =============================================================================
# Core Functions
# =============================================================================


def calculate_overdue_and_stage(due_date_str):
    """Calculates overdue days and returns days, default stage, and risk level."""
    due_date = pd.to_datetime(due_date_str)
    today = datetime.now()
    days = (today - due_date).days
    days = max(days, 0)

    if days <= 0:
        stage = "Not Overdue"
    elif 1 <= days <= 7:
        stage = "Stage 1"
    elif 8 <= days <= 14:
        stage = "Stage 2"
    elif 15 <= days <= 21:
        stage = "Stage 3"
    elif 22 <= days <= 30:
        stage = "Stage 4"
    else:
        stage = "Escalate"

    if days <= 0:
        risk = "Low Risk"
    elif days <= 14:
        risk = "Medium Risk"
    elif days <= 30:
        risk = "High Risk"
    else:
        risk = "Critical"

    return days, stage, risk


def sync_csv_to_db(df):
    """
    Saves each CSV row into the invoices table.

    Duplicate invoice_no:
    - Because invoice_no is the PRIMARY KEY, a second INSERT would error.
    - We first SELECT. If the invoice exists, we UPDATE core fields but keep
      the user's current stage and send_status (so overrides are preserved).
    - If it does not exist, we INSERT a fresh row with default stage/status.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    for _, row in df.iterrows():
        inv = row["invoice_no"]
        client = row["client_name"]
        amount = row["amount"]
        due_date_str = str(row["due_date"])
        email = row["email"]

        days, default_stage, risk = calculate_overdue_and_stage(due_date_str)

        c.execute("SELECT stage, send_status FROM invoices WHERE invoice_no=?", (inv,))
        existing = c.fetchone()

        if existing:
            # Invoice already in DB: refresh amounts/dates, keep stage + send_status
            c.execute(
                """
                UPDATE invoices
                SET client_name=?, amount=?, due_date=?, email=?, overdue_days=?, risk_level=?
                WHERE invoice_no=?
                """,
                (client, amount, due_date_str, email, days, risk, inv),
            )
        else:
            # New invoice: insert full row (no duplicate invoice_no)
            c.execute(
                """
                INSERT INTO invoices (
                    invoice_no, client_name, amount, due_date, email,
                    overdue_days, stage, risk_level, send_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (inv, client, amount, due_date_str, email, days, default_stage, risk, "Pending"),
            )

    conn.commit()
    conn.close()


def load_invoices_from_db():
    """Reads all rows from invoices into a pandas DataFrame."""
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM invoices", conn)
    conn.close()
    return df


def load_audit_logs():
    """
    Loads every audit row from SQLite (newest first).
    This is the only place the UI should read audits from — not session_state.
    """
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM audit_logs ORDER BY timestamp DESC", conn)
    conn.close()
    return df


def insert_audit_log(invoice_no, action, old_stage, new_stage, reason):
    """
    Appends one row to the audit_logs table.

    SQLite is the source of truth: audits survive refresh, rerun, and closing the app.
    We always store a human-readable timestamp string for simple sorting in SQL.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute(
        """
        INSERT INTO audit_logs (timestamp, invoice_no, action, old_stage, new_stage, reason)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (timestamp, invoice_no, action, old_stage, new_stage, reason),
    )
    conn.commit()
    conn.close()


def update_invoice_stage(invoice_no, new_stage):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE invoices SET stage=? WHERE invoice_no=?", (new_stage, invoice_no))
    conn.commit()
    conn.close()


def update_send_status(
    invoice_no,
    reason="Send status updated to Sent",
    audit_action="Send Status Updated",
):
    """
    Sets send_status to Sent and records the change in audit_logs.

    old_stage / new_stage columns are reused here to store the previous and new
    send_status values (same two TEXT columns as for escalation — keeps the schema simple).

    audit_action lets callers label the row (for example "Real Email Sent" after Gmail SMTP).
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT send_status FROM invoices WHERE invoice_no=?", (invoice_no,))
    row = c.fetchone()
    if row is None:
        conn.close()
        return

    old_status = row[0]

    c.execute("UPDATE invoices SET send_status='Sent' WHERE invoice_no=?", (invoice_no,))
    conn.commit()
    conn.close()

    insert_audit_log(invoice_no, audit_action, old_status, "Sent", reason)


def send_real_email(sender_email, app_password, receiver_email, subject, body):
    """
    Sends one plain-text email through Gmail using smtplib (standard library only).

    Parameters
    ----------
    sender_email : str
        Your full Gmail address (must match the account that created the App Password).
    app_password : str
        A 16-character Google "App Password" — never your normal Gmail password.
    receiver_email : str
        The client's inbox from the invoice row.
    subject / body : str
        Already generated follow-up text.

    Returns
    -------
    (success: bool, message: str)
        On failure we return (False, error text) so Streamlit can show st.error without crashing.
    """
    try:
        # --- Step 1: build the email object (headers + body) ---
        # MIMEMultipart is a container; MIMEText holds the human-readable message.
        msg = MIMEMultipart()
        msg["From"] = sender_email
        msg["To"] = receiver_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        # --- Step 2: connect to Gmail's SMTP server on port 587 ---
        # Port 587 expects you to upgrade the connection with STARTTLS (encrypted tunnel).
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.ehlo()  # say hello to the server (identify our client)
        server.starttls()  # upgrade the connection to TLS encryption
        server.ehlo()  # hello again after TLS

        # --- Step 3: log in using the Gmail address + App Password ---
        server.login(sender_email, app_password)

        # --- Step 4: send and disconnect ---
        # send_message reads From/To from the MIME object and formats the raw email for you.
        server.send_message(msg)
        server.quit()

        return True, "Email sent successfully via Gmail SMTP."
    except Exception as e:
        # Do not re-raise: the Streamlit app keeps running and we show the error in the UI.
        return False, str(e)


def generate_email_text_templates(row):
    """
    Original template-based generator (no network).
    Used as a safe fallback when Groq is unavailable or returns bad data.
    """
    client = row["client_name"].split()[0]
    amount = row["amount"]
    inv = row["invoice_no"]
    stage = row["stage"]
    days = row["overdue_days"]

    greetings = [
        f"Hi {client}, hope you're having a good week.",
        f"Hello {client},",
        f"Dear {client}, hope this finds you well.",
    ]
    closings = [
        "Best regards,\nFinance Team",
        "Sincerely,\nAccounts Receivable",
        "Thank you,\nFinance Department",
    ]

    greet = random.choice(greetings)
    close = random.choice(closings)

    if stage == "Stage 1":
        subject = f"Friendly Reminder: Invoice {inv} is Due"
        body = f"{greet}\n\nJust a friendly reminder that invoice {inv} for ₹{amount:,.2f} is {days} days overdue. We'd appreciate it if you could process the payment at your earliest convenience.\n\n{close}"
    elif stage == "Stage 2":
        subject = f"Payment Request: Invoice {inv} is Overdue"
        body = f"{greet}\n\nOur records indicate that invoice {inv} for ₹{amount:,.2f} is now {days} days overdue. Please arrange for payment as soon as possible to avoid any late fees. Let us know if you need any clarification.\n\n{close}"
    elif stage == "Stage 3":
        subject = f"Urgent: Formal Notice Regarding Invoice {inv}"
        body = f"Attention {client},\n\nThis is a formal warning regarding your unpaid invoice {inv} amounting to ₹{amount:,.2f}. The payment is delayed by {days} days. We require immediate payment to keep your account in good standing.\n\n{close}"
    elif stage == "Stage 4":
        subject = f"Final Notice: Imminent Escalation for Invoice {inv}"
        body = f"URGENT: {client},\n\nThis is our final notice regarding invoice {inv} (₹{amount:,.2f}). Your payment is {days} days late. Failure to pay immediately will result in your account being suspended and escalated for collection.\n\nImmediate Action Required.\n\n{close}"
    elif stage in ["Escalate", "Escalate Manually"]:
        subject = "N/A"
        body = "Requires manual finance/legal review. No automated email generated."
    else:
        subject = "N/A"
        body = "Invoice not overdue or marked paid. No email needed."

    return subject, body


def _strip_json_fence(text: str) -> str:
    """Removes optional ```json ... ``` wrappers some models add around JSON."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    text = text.strip()
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _groq_generate_reminder(row, api_key):
    """
    Calls Groq's chat completions API and expects a JSON object with subject + body.

    This is the primary "AI" path. If anything goes wrong, the caller falls back
    to generate_email_text_templates().
    """
    stage = row["stage"]
    client_name = str(row["client_name"])
    invoice_no = str(row["invoice_no"])
    amount = row["amount"]
    due_date = str(row["due_date"])
    overdue_days = int(row["overdue_days"])

    # Tone rules mirror the escalation ladder used in the dashboard.
    if stage == "Stage 1":
        tone = "Warm, polite payment reminder. Assume an innocent oversight."
    elif stage == "Stage 2":
        tone = "Polite but firm; request payment timeline and confirmation."
    elif stage == "Stage 3":
        tone = "Formal and serious; stress consequences of continued delay; ask for response within 48 hours."
    elif stage == "Stage 4":
        tone = "Final notice tone; mention possible escalation to collections/legal; urgent payment required."
    else:
        tone = "Professional standard collections tone."

    system_msg = (
        "You are a Finance Credit Controller. Write concise, professional payment reminder emails. "
        "Sign off as Finance Department or Accounts Receivable (pick one). "
        "Never use placeholder brackets like [Company]. "
        "Respond with VALID JSON ONLY, one object with exactly two string keys: "
        "\"subject\" and \"body\". Use plain text in body (newlines allowed). No markdown fences."
    )

    user_msg = f"""Write one email for this overdue invoice.
Escalation stage: {stage}
Tone guidance: {tone}

Invoice details (use all of them in the email):
- Client name: {client_name}
- Invoice number: {invoice_no}
- Amount due (INR): ₹{float(amount):,.2f}
- Due date: {due_date}
- Days overdue: {overdue_days}

JSON format: {{"subject": "...", "body": "..."}}"""

    # Groq client: pass the API key from the environment (loaded via dotenv above).
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

    raw = completion.choices[0].message.content
    if not raw:
        raise ValueError("Empty response from Groq")

    cleaned = _strip_json_fence(raw)
    data = json.loads(cleaned)
    subject = str(data["subject"]).strip()
    body = str(data["body"]).strip()
    if not subject or not body:
        raise ValueError("Groq JSON missing subject or body")
    return subject, body


def generate_email_text(row):
    """
    Try Groq first for real AI wording; fall back to templates if anything fails.

    Returns:
        subject, body, warning_message
        warning_message is None when Groq succeeds, otherwise a short reason for the UI.
    """
    template_subject, template_body = generate_email_text_templates(row)

    # Fallback mechanism: these cases stay on templates (same as before — no API call).
    if template_subject == "N/A":
        return template_subject, template_body, None

    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        # No key: quietly use templates (no Streamlit warning).
        return template_subject, template_body, None

    try:
        subject, body = _groq_generate_reminder(row, api_key)
        return subject, body, None
    except Exception as e:
        # Fallback mechanism: never break the app — use templates and surface a warning string.
        return (
            template_subject,
            template_body,
            f"Groq API error ({e}). Using template email instead.",
        )


# =============================================================================
# Main App Layout
# =============================================================================
def main():
    st.title("💰 Finance Credit Follow-Up Dashboard")
    st.write(
        "A simple tool to track overdue invoices, manage risk, and generate follow-up emails. "
        "SQLite stores your data in **finance_agent.db** next to this script."
    )

    # -------------------------------------------------------------------------
    # Session state (place near the start of main(), before heavy UI logic)
    # -------------------------------------------------------------------------
    # We keep a few keys so you can grow the app later without losing patterns.
    # Audit logs are NEVER stored in session_state — only in SQLite (see insert_audit_log).
    st.session_state.pop("audit_logs", None)

    if "last_csv_name" not in st.session_state:
        st.session_state["last_csv_name"] = None
    if "upload_success" not in st.session_state:
        st.session_state["upload_success"] = False
    # When True, we keep showing the generated-email expanders even after inner buttons rerun the app.
    if "email_drafts" not in st.session_state:
        st.session_state["email_drafts"] = None

    # --- Sidebar ---
    st.sidebar.header("📁 Upload Data")
    uploaded_file = st.sidebar.file_uploader("Upload Invoices CSV", type=["csv"])

    if uploaded_file is not None:
        try:
            df_upload = pd.read_csv(uploaded_file)
            sync_csv_to_db(df_upload)
            st.session_state["last_csv_name"] = uploaded_file.name
            st.session_state["upload_success"] = True
            # New data: drop cached email panel so subjects/bodies match the new CSV.
            st.session_state["email_drafts"] = None
            st.sidebar.success("CSV uploaded and saved to SQLite (duplicate invoice_no rows are updated, not duplicated).")
        except Exception as e:
            st.session_state["upload_success"] = False
            st.sidebar.error(f"Error parsing CSV: {e}")

    st.sidebar.divider()
    st.sidebar.header("📧 Gmail SMTP")
    st.sidebar.write("Real sending uses Gmail on port 587 (TLS). Use an **App Password**, not your normal password.")
    gmail_sender = st.sidebar.text_input("Sender Gmail address", placeholder="you@gmail.com")
    gmail_app_password = st.sidebar.text_input("Gmail App Password", type="password", placeholder="16-character app password")

    st.sidebar.divider()
    st.sidebar.header("🛠️ Tech Stack")
    st.sidebar.markdown(
        """
    - **Python & SQLite (sqlite3)**
    - **Streamlit**
    - **Pandas & Plotly**
    - **smtplib + Gmail SMTP (real send)**
    - **Groq (Llama 3.3) + dotenv for AI drafts, with template fallback**

    *Put `GROQ_API_KEY=...` in a `.env` file next to `app.py`.*
    """
    )

    # Always load the latest invoices from SQLite
    df = load_invoices_from_db()

    # -------------------------------------------------------------------------
    # NEW UI SECTION: show raw SQLite tables (place after you load `df`)
    # -------------------------------------------------------------------------
    st.subheader("🗄️ Database Contents (SQLite)")
    st.caption(f"Database file: `{DB_PATH}`")
    db_invoices_df = load_invoices_from_db()
    db_audit_df = load_audit_logs()
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Table: invoices**")
        if len(db_invoices_df) == 0:
            st.info("No rows in invoices yet. Upload a CSV in the sidebar.")
        else:
            st.dataframe(db_invoices_df, use_container_width=True)
    with c2:
        st.markdown("**Table: audit_logs**")
        if len(db_audit_df) == 0:
            st.info("No rows in audit_logs yet.")
        else:
            st.dataframe(db_audit_df, use_container_width=True)

    st.divider()

    if len(df) == 0:
        st.info("👈 Upload a CSV file from the sidebar to populate the dashboard.")
        return

    try:
        overdue_df = df[df["overdue_days"] > 0]

        # ==========================================
        # 1. Executive Summary
        # ==========================================
        st.subheader("📊 Executive Summary")

        total_invoices = len(df)
        total_overdue = overdue_df["amount"].sum()
        escalated_cases = len(df[df["stage"].isin(["Escalate", "Escalate Manually"])])
        avg_overdue_days = int(overdue_df["overdue_days"].mean()) if len(overdue_df) > 0 else 0

        highest_client = "None"
        if len(overdue_df) > 0:
            highest_client_row = overdue_df.sort_values(by=["overdue_days", "amount"], ascending=False).iloc[0]
            highest_client = highest_client_row["client_name"]

        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Total Invoices", total_invoices)
        col2.metric("Total Outstanding", f"₹{total_overdue:,.0f}")
        col3.metric("Escalated Cases", escalated_cases)
        col4.metric("Avg Overdue Days", f"{avg_overdue_days} Days")
        col5.metric("Highest Risk Client", highest_client)

        st.divider()

        # ==========================================
        # 2. Charts & Data Table
        # ==========================================
        st.subheader("📈 Escalation Overview")

        stage_counts = df["stage"].value_counts().reset_index()
        stage_counts.columns = ["Stage", "Count"]
        fig = px.pie(stage_counts, values="Count", names="Stage", hole=0.4)
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("📋 Invoice Directory")
        st.dataframe(
            df[
                [
                    "invoice_no",
                    "client_name",
                    "amount",
                    "due_date",
                    "overdue_days",
                    "stage",
                    "risk_level",
                    "send_status",
                ]
            ],
            use_container_width=True,
        )

        st.divider()

        # ==========================================
        # 3. Basic Override Feature
        # ==========================================
        st.subheader("⚙️ Human-in-the-Loop Override")
        st.write("Use the expanders below to manually override the escalation stage.")

        if len(overdue_df) == 0:
            st.success("No overdue invoices to override!")
        else:
            for index, row in overdue_df.iterrows():
                inv = row["invoice_no"]
                client = row["client_name"]
                curr_stage = row["stage"]

                with st.expander(f"{client} - {inv} (Current: {curr_stage})"):
                    col_form1, col_form2 = st.columns(2)

                    with col_form1:
                        new_stage = st.selectbox(
                            "Select New Stage",
                            [
                                "Keep Current Stage",
                                "Stage 1",
                                "Stage 2",
                                "Stage 3",
                                "Stage 4",
                                "Escalate Manually",
                                "Mark Paid",
                            ],
                            key=f"stage_{inv}",
                        )
                    with col_form2:
                        reason = st.text_input("Reason for override", key=f"reason_{inv}")

                    if st.button("Apply Override", key=f"btn_{inv}"):
                        if new_stage != "Keep Current Stage":
                            update_invoice_stage(inv, new_stage)
                            insert_audit_log(
                                inv,
                                "Manual Override",
                                curr_stage,
                                new_stage,
                                reason if reason else "No reason provided",
                            )

                            st.success(f"Successfully overridden {inv} to {new_stage}!")
                            st.rerun()

        st.divider()

        # ==========================================
        # 4. Audit Log Table
        # ==========================================
        st.subheader("🛡️ Audit Logs")
        audit_df = load_audit_logs()
        if len(audit_df) > 0:
            st.dataframe(audit_df, use_container_width=True)
        else:
            st.info("No audit events in SQLite yet. Overrides, generated emails, and send-status changes will appear here.")

        st.divider()

        # ==========================================
        # 5. Email Generator & Export
        # ==========================================
        st.subheader("🤖 AI Follow-Up Generator")
        st.caption(
            "Drafts use **Groq** (model llama-3.3-70b-versatile) when `GROQ_API_KEY` is set in `.env`; "
            "otherwise templates are used. **Simulate Send Email** is a dry run. **Send Real Email** uses Gmail SMTP."
        )

        if st.button("Generate Follow-Up Emails"):
            if len(overdue_df) == 0:
                st.session_state["email_drafts"] = None
                st.success("No overdue invoices. No emails needed!")
            else:
                # Build drafts once per click and remember them in session_state.
                # Otherwise, when you click "Send Real Email", Streamlit reruns and the outer
                # "Generate" button is no longer "pressed", so this whole section would vanish.
                drafts = []
                groq_fallback_warnings = []
                for index, row in overdue_df.iterrows():
                    subj, body, groq_warn = generate_email_text(row)
                    if groq_warn:
                        groq_fallback_warnings.append(groq_warn)
                    inv = row["invoice_no"]

                    insert_audit_log(
                        inv,
                        "Email Generated",
                        str(row["stage"]),
                        subj if subj != "N/A" else "N/A",
                        "Follow-up email text generated (review before real SMTP send).",
                    )

                    drafts.append(
                        {
                            "invoice_no": inv,
                            "client_name": row["client_name"],
                            "email": row["email"],
                            "stage": row["stage"],
                            "subject": subj,
                            "body": body,
                        }
                    )
                # If Groq failed (or key missing), tell the user once per unique reason.
                for msg in dict.fromkeys(groq_fallback_warnings):
                    st.warning(msg)
                st.session_state["email_drafts"] = drafts

        # Show cached drafts (same subjects/bodies until user clicks Generate again).
        drafts = st.session_state.get("email_drafts")
        if drafts:
            emails_data = []
            for i, draft in enumerate(drafts):
                inv = draft["invoice_no"]
                client = draft["client_name"]
                recipient = draft["email"]
                subj = draft["subject"]
                body = draft["body"]
                stage_label = draft["stage"]

                # Always read latest send_status from SQLite (e.g. after a real send + rerun).
                match = df[df["invoice_no"] == inv]
                send_status = match["send_status"].iloc[0] if len(match) else "Pending"

                emails_data.append(
                    {
                        "invoice_no": inv,
                        "client_name": client,
                        "email": recipient,
                        "stage": stage_label,
                        "subject": subj,
                        "body": body,
                        "send_status": send_status,
                    }
                )

                with st.expander(f"Email for {client} ({stage_label})"):
                    st.write(f"**To:** {recipient}")
                    st.write(f"**Subject:** {subj}")
                    st.text_area("Body", value=body, height=150, disabled=True, key=f"email_{i}_{inv}")
                    if send_status == "Sent":
                        st.info("This invoice is already marked as Sent in the database.")
                    else:
                        can_send_real = subj != "N/A" and bool(str(body).strip())
                        btn_sim, btn_real = st.columns(2)
                        with btn_sim:
                            if st.button("Simulate Send Email", key=f"sim_send_{inv}"):
                                st.success(
                                    f"Dry run only: would send to **{recipient}** with subject \"{subj}\". "
                                    "No SMTP call and no database changes."
                                )
                        with btn_real:
                            if st.button("Send Real Email", key=f"real_send_{inv}"):
                                if not gmail_sender or not gmail_app_password:
                                    st.warning("Please enter your Sender Gmail address and App Password in the sidebar.")
                                elif not can_send_real:
                                    st.warning("This row has no sendable subject/body for this stage (N/A).")
                                else:
                                    ok, err_msg = send_real_email(
                                        gmail_sender,
                                        gmail_app_password,
                                        recipient,
                                        subj,
                                        body,
                                    )
                                    if ok:
                                        st.success("Email sent successfully via Gmail SMTP.")
                                        update_send_status(
                                            inv,
                                            reason=f"Gmail SMTP to {recipient}; subject: {subj}",
                                            audit_action="Real Email Sent",
                                        )
                                        st.rerun()
                                    else:
                                        st.error(f"SMTP send failed (app still running): {err_msg}")

            st.write("### 📤 Export Generated Emails")
            emails_df = pd.DataFrame(emails_data)

            col_csv, col_json = st.columns(2)
            with col_csv:
                csv_data = emails_df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="Download Emails as CSV",
                    data=csv_data,
                    file_name="follow_up_emails.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            with col_json:
                json_data = emails_df.to_json(orient="records").encode("utf-8")
                st.download_button(
                    label="Download Emails as JSON",
                    data=json_data,
                    file_name="generated_email_report.json",
                    mime="application/json",
                    use_container_width=True,
                )

        st.divider()

        # ==========================================
        # 6. Architecture / Workflow Section
        # ==========================================
        st.subheader("⚙️ System Workflow")
        st.markdown(
            """
        <div style="text-align: center; font-size: 16px; font-weight: bold; color: #4b5563;">
            Upload CSV <br>
            ↓ <br>
            Save to SQLite Database <br>
            ↓ <br>
            Detect Overdue Invoices <br>
            ↓ <br>
            Generate AI Follow-Up Emails <br>
            ↓ <br>
            Human Review & Override <br>
            ↓ <br>
            Simulate or Send Real Emails via Gmail SMTP <br>
            ↓ <br>
            Export Reports
        </div>
        """,
            unsafe_allow_html=True,
        )

    except Exception as e:
        st.error(f"Error processing data: {e}")


if __name__ == "__main__":
    main()
