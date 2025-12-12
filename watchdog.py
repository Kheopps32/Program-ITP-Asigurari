import os, smtplib, logging, requests
from email.message import EmailMessage
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

# ---------- Config din env ----------
LOCAL_TZ         = os.getenv("TARGET_LOCAL_TZ", "Europe/Bucharest")
EXPECTED_HOUR    = int(os.getenv("TARGET_LOCAL_HOUR", "8"))   # ora locală la care ar trebui să fi rulat botul principal
GRACE_MIN        = int(os.getenv("WATCH_GRACE_MIN", "90"))    # fereastra de grație după ora așteptată
WORKFLOW_FILE    = os.getenv("WATCH_WORKFLOW_FILE", "run_reminder.yml")  # numele fișierului workflow-ului principal
FORCE_ALERT      = os.getenv("WATCH_FORCE_ALERT", "0") == "1" # dacă e 1, trimite mail de test imediat

# Email (aceleași secrete ca botul principal)
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "")
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
DEST_EMAIL   = os.getenv("DEST_EMAIL", SENDER_EMAIL)
SMTP_HOST    = os.getenv("SMTP_HOST", "smtp.office365.com")
SMTP_PORT    = int(os.getenv("SMTP_PORT", "587"))

# GitHub (Actions le expune implicit)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")             # corect: din ${{ github.token }}
REPO         = os.getenv("GITHUB_REPOSITORY")        # ex. owner/repo

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def _clean_header(s: str) -> str:
    """Elimină CR/LF și spații duble din header-ele de email."""
    return " ".join((s or "").replace("\r", " ").replace("\n", " ").split())

def send_mail(subject: str, body: str):
    from_addr = _clean_header(SENDER_EMAIL)
    to_addr   = _clean_header(DEST_EMAIL)
    subj      = _clean_header(subject)

    if not from_addr or not to_addr:
        raise SystemExit("SENDER_EMAIL/DEST_EMAIL lipsesc sau sunt invalide.")

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subj
    msg.set_content(body)

    host = _clean_header(SMTP_HOST) or "smtp.office365.com"
    try:
        port = int(SMTP_PORT)
    except Exception:
        port = 587

    with smtplib.SMTP(host, port) as s:
        s.starttls()
        s.login(from_addr, APP_PASSWORD)
        s.send_message(msg)

def main():
    # Validări de bază
    if not (SENDER_EMAIL and APP_PASSWORD and DEST_EMAIL):
        raise SystemExit("Lipsesc variabilele de e-mail (SENDER_EMAIL/APP_PASSWORD/DEST_EMAIL).")
    if not (GITHUB_TOKEN and REPO and WORKFLOW_FILE):
        raise SystemExit("Lipsesc GITHUB_TOKEN/REPO/WORKFLOW_FILE.")

    # TEST FORȚAT – trimite email imediat și iese
    if FORCE_ALERT:
        send_mail(
            "Watchdog TEST: fortat",
            "Acesta este un test fortat trimis de watchdog."
        )
        logging.info("Alertă de test trimisă (FORCE_ALERT=1).")
        return

    now_local = datetime.now(ZoneInfo(LOCAL_TZ))

    # alertează DOAR după ora așteptată + grație
    target_today = now_local.replace(hour=EXPECTED_HOUR, minute=0, second=0, microsecond=0)
    if now_local < target_today + timedelta(minutes=GRACE_MIN):
        logging.info("Încă nu am trecut de fereastra de grație. Ies.")
        return

    # miezul nopții local (azi) convertit în UTC — pragul "de azi"
    midnight_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    midnight_utc = midnight_local.astimezone(timezone.utc)

    # interogăm ultimele run-uri ale workflow-ului principal
    url = f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW_FILE}/runs?per_page=20"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    runs = r.json().get("workflow_runs", [])

    # căutăm o rulare cu succes de AZI (după miezul nopții local)
    ok_today = None
    last_info = "n/a"
    for run in runs:
        created = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
        conclusion = run.get("conclusion")
        status = run.get("status")
        last_info = f"{status}/{conclusion} @ {created.isoformat()}Z"
        if created >= midnight_utc and conclusion == "success":
            ok_today = run
            break

    if ok_today:
        logging.info("Workflow-ul principal a rulat cu succes azi. Ies.")
        return

    # dacă nu a existat run reușit azi -> trimitem alertă
    subject = "Watchdog: reminder bot NU a rulat azi"
    body = (
        f"Salut,\n\n"
        f"Watchdog-ul nu a găsit o rulare cu succes a workflow-ului principal astăzi (zona {LOCAL_TZ}).\n"
        f"Workflow verificat: {WORKFLOW_FILE}\n"
        f"Repo: {REPO}\n"
        f"Oră așteptată: {EXPECTED_HOUR:02d}:00 {LOCAL_TZ} (+{GRACE_MIN} min grație)\n"
        f"Ultima rulare văzută: {last_info}\n\n"
        f"Verifică tab-ul Actions în GitHub.\n"
    )
    send_mail(subject, body)
    logging.info("Alertă trimisă (nu s-a găsit run reușit azi).")

if __name__ == "__main__":
    main()
