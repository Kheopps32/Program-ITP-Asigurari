import os, smtplib, logging, requests
from email.message import EmailMessage
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

# -------- Config --------
LOCAL_TZ = os.getenv("TARGET_LOCAL_TZ", "Europe/Bucharest")
EXPECTED_HOUR = int(os.getenv("TARGET_LOCAL_HOUR", "8"))  # ora locală la care trebuie să fi rulat botul
WORKFLOW_FILE = os.getenv("WATCH_WORKFLOW_FILE", "run-reminder.yml")  # numele fișierului workflow-ului principal (ex. blank.yml sau run-reminder.yml)
GRACE_MIN = int(os.getenv("WATCH_GRACE_MIN", "90"))  # fereastra de grație după ora așteptată

# Email (folosește aceleași secrete ca botul principal)
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "")
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
DEST_EMAIL   = os.getenv("DEST_EMAIL", SENDER_EMAIL)
SMTP_HOST    = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT    = int(os.getenv("SMTP_PORT", "587"))

# GitHub
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")  # Actions îl expune automat
REPO = os.getenv("GITHUB_REPOSITORY")     # "owner/repo"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def send_mail(subject: str, body: str):
    msg = EmailMessage()
    msg["From"] = SENDER_EMAIL
    msg["To"] = DEST_EMAIL
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.starttls()
        s.login(SENDER_EMAIL, APP_PASSWORD)
        s.send_message(msg)

def main():
    if not (SENDER_EMAIL and APP_PASSWORD and DEST_EMAIL):
        raise SystemExit("Lipsesc variabilele de e-mail.")

    if not (GITHUB_TOKEN and REPO and WORKFLOW_FILE):
        raise SystemExit("Lipsesc GITHUB_TOKEN/REPO/WORKFLOW_FILE.")

    now_local = datetime.now(ZoneInfo(LOCAL_TZ))
    # rulează din oră în oră, dar alertează DOAR dacă suntem după ora așteptată + grație
    target_today = now_local.replace(hour=EXPECTED_HOUR, minute=0, second=0, microsecond=0)
    if now_local < target_today + timedelta(minutes=GRACE_MIN):
        logging.info("Încă nu am trecut de fereastra de grație. Ies.")
        return

    # calculăm miezul nopții local (a
