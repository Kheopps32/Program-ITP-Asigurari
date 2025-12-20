import os
import smtplib
from email.message import EmailMessage


def tail_text(path: str, max_lines: int = 120) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[-max_lines:]).strip()
    except FileNotFoundError:
        return f"(Nu am gasit {path})"
    except Exception as e:
        return f"(Eroare la citirea {path}: {e})"


def ensure_env():
    missing = []
    for k in ["SENDER_EMAIL", "APP_PASSWORD", "DEST_EMAIL"]:
        if not os.getenv(k, "").strip():
            missing.append(k)
    if missing:
        raise SystemExit("Lipsesc variabilele: " + ", ".join(missing))


def send_mail(subject: str, body: str):
    sender = os.getenv("SENDER_EMAIL").strip()
    password = os.getenv("APP_PASSWORD").strip()
    dest = os.getenv("DEST_EMAIL").strip()

    host = os.getenv("SMTP_HOST", "smtp.office365.com").strip()
    port = int(os.getenv("SMTP_PORT", "587"))

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = dest
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(host, port) as s:
        s.starttls()
        s.login(sender, password)
        s.send_message(msg)


def main():
    ensure_env()

    repo = os.getenv("GITHUB_REPOSITORY", "")
    workflow = os.getenv("GITHUB_WORKFLOW", "")
    run_id = os.getenv("GITHUB_RUN_ID", "")
    server = os.getenv("GITHUB_SERVER_URL", "https://github.com")

    run_url = f"{server}/{repo}/actions/runs/{run_id}" if repo and run_id else "(run url indisponibil)"

    log_path = os.getenv("LOG_PATH", "app.log")
    log_tail = tail_text(log_path)

    subject = f"[ALERTA] Workflow FAILED: {workflow} ({repo})"
    body = (
        f"Reminder bot NU a rulat cu succes.\n\n"
        f"Repo: {repo}\n"
        f"Workflow: {workflow}\n"
        f"Run: {run_url}\n\n"
        f"Ultimele linii din {log_path}:\n"
        f"{'-'*40}\n"
        f"{log_tail}\n"
        f"{'-'*40}\n"
    )

    send_mail(subject, body)


if __name__ == "__main__":
    main()
