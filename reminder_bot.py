import os
import csv
import smtplib
from datetime import date, datetime, timedelta
from email.message import EmailMessage
import logging
from logging.handlers import RotatingFileHandler

import pandas as pd
from dateutil import parser as dateparser

# ------------------- Config -------------------
CSV_FILE = "camioane.csv"

# VARIANTA RAPIDĂ (fără lag): export endpoint
#     https://docs.google.com/spreadsheets/d/<FILE_ID>/export?format=csv&gid=<GID_TAB>
GSHEET_EXPORT_FILE_ID = os.getenv("GSHEET_EXPORT_FILE_ID", "").strip()
GSHEET_EXPORT_GID     = os.getenv("GSHEET_EXPORT_GID", "").strip()

# Fallback: Publish to web CSV (poate avea lag)
GSHEET_CSV_URL = os.getenv("GSHEET_CSV_URL", "").strip()

SENT_LOG = "sent_log.csv"          # doar pt. dubluri în aceeași rulare (nu persistent)
TRIGGERS = {30, 15, 7, 4, 1, 0}    # include și "azi"
DATE_FORMAT_OUTPUT = "%Y-%m-%d"

SENDER_EMAIL = os.getenv("SENDER_EMAIL", "").strip()
APP_PASSWORD = os.getenv("APP_PASSWORD", "").strip()
DEST_EMAIL   = os.getenv("DEST_EMAIL", "alextransbz@gmail.com").strip()

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.office365.com").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

# ------------------- Logging -------------------
logger = logging.getLogger("reminder")
logger.setLevel(logging.INFO)
handler = RotatingFileHandler("app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(handler)

# ------------------- Helpers -------------------
def ensure_env():
    missing = []
    if not SENDER_EMAIL:
        missing.append("SENDER_EMAIL")
    if not APP_PASSWORD:
        missing.append("APP_PASSWORD")
    if missing:
        raise SystemExit(
            "Lipsesc variabilele: " + ", ".join(missing) +
            ". Configureaza secretele in GitHub (Settings → Secrets and variables → Actions)."
        )

def parse_date(value):
    if pd.isna(value):
        return None
    val = str(value).strip()
    if not val or val.lower() in {"na", "none", "nan"}:
        return None
    try:
        dt = dateparser.parse(val, dayfirst=True)
        return dt.date()
    except Exception:
        logger.warning("Nu pot interpreta data: %r", value)
        return None

def read_sent_log():
    seen = set()
    if not os.path.exists(SENT_LOG):
        return seen
    with open(SENT_LOG, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (
                (row.get("nr_masina","") or "").strip().upper(),
                (row.get("tip","") or "").strip().upper(),
                (row.get("data_expirarii","") or "").strip(),
                str(row.get("days_left","")).strip(),
            )
            seen.add(key)
    return seen

def append_sent_log(nr_masina, tip, data_expirarii, days_left):
    file_exists = os.path.exists(SENT_LOG)
    with open(SENT_LOG, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["sent_at","nr_masina","tip","data_expirarii","days_left","dest"])
        if not file_exists:
            writer.writeheader()
        writer.writerow({
            "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "nr_masina": nr_masina,
            "tip": tip,
            "data_expirarii": data_expirarii,
            "days_left": str(days_left),
            "dest": DEST_EMAIL
        })

def send_mail(subject, body):
    msg = EmailMessage()
    msg["From"] = SENDER_EMAIL
    msg["To"] = DEST_EMAIL
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.starttls()
        s.login(SENDER_EMAIL, APP_PASSWORD)
        s.send_message(msg)

def _cache_bust_url(url: str) -> str:
    stamp = int(datetime.now().timestamp())
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}_={stamp}"

def _export_csv_url(file_id: str, gid: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{file_id}/export?format=csv&gid={gid}"

def load_fleet_df() -> pd.DataFrame:
    # Preferă export endpoint (fără lag)
    if GSHEET_EXPORT_FILE_ID and GSHEET_EXPORT_GID:
        source = _cache_bust_url(_export_csv_url(GSHEET_EXPORT_FILE_ID, GSHEET_EXPORT_GID))
        logger.info("Incarc datele din Google Sheets (export CSV, fara lag).")
        df = pd.read_csv(source, dtype=str, encoding="utf-8", sep=None, engine="python")
    elif GSHEET_CSV_URL:
        source = _cache_bust_url(GSHEET_CSV_URL)
        logger.info("Incarc datele din Google Sheets CSV (Publish to web).")
        df = pd.read_csv(source, dtype=str, encoding="utf-8", sep=None, engine="python")
    else:
        if not os.path.exists(CSV_FILE):
            raise SystemExit(
                f"Nu gasesc {CSV_FILE} si nu ai setat GSHEET_EXPORT_* sau GSHEET_CSV_URL."
            )
        logger.info("Incarc datele din fisierul local: %s", CSV_FILE)
        df = pd.read_csv(CSV_FILE, dtype=str, encoding="utf-8", sep=None, engine="python")

    if not df.empty:
        df = df.dropna(how="all")
    return df

def plural_zi_zile(n: int) -> str:
    return "zi" if abs(n) == 1 else "zile"

# ------------------- Mesaje -------------------
def build_future_msg(tip: str, prefix_marca: str, nr: str, d: date, days_left: int):
    subject = f"Expira {tip.lower()} la {prefix_marca}{nr} in {days_left} {plural_zi_zile(days_left)}"
    body = (
        f"Avertizare expirare: {tip}\n"
        f"Masina: {prefix_marca}{nr}\n"
        f"Data expirarii: {d.strftime(DATE_FORMAT_OUTPUT)}\n"
        f"Au ramas: {days_left} {plural_zi_zile(days_left)}\n\n"
        f"Acest mesaj a fost generat automat."
    )
    return subject, body

def build_today_msg(tip: str, prefix_marca: str, nr: str, d: date):
    subject = f"Expira AZI {tip.lower()} la {prefix_marca}{nr}"
    body = (
        f"AVERTIZARE: {tip} EXPIRA ASTAZI\n"
        f"Masina: {prefix_marca}{nr}\n"
        f"Data expirarii: {d.strftime(DATE_FORMAT_OUTPUT)}\n\n"
        f"Te rugam sa te ocupi de reinnoire in cursul zilei de azi."
    )
    return subject, body

def build_overdue_msg(tip: str, prefix_marca: str, nr: str, d: date, overdue_days: int):
    subject = (
        f"{tip.capitalize()} la {prefix_marca}{nr} este EXPIRAT\u0102 de "
        f"{overdue_days} {plural_zi_zile(overdue_days)}"
    )
    body = (
        f"AVERTIZARE: {tip} EXPIRAT\u0102\n"
        f"Ma\u0219ina: {prefix_marca}{nr}\n"
        f"Data expir\u0103rii: {d.strftime(DATE_FORMAT_OUTPUT)}\n"
        f"Dep\u0103\u0219ire: {overdue_days} {plural_zi_zile(overdue_days)}\n\n"
        f"Te rug\u0103m s\u0103 actualizezi documentul c\u00E2t mai rapid."
    )
    return subject, body

# ------------------- Core -------------------
def main():
    ensure_env()
    today = date.today()
    df = load_fleet_df()

    logger.info("Rows in DF: %s, columns: %s", df.shape[0], list(df.columns))

    # Coloane obligatorii: fără asigurare_expira
    required_cols = {"nr_masina", "rovinieta_expira", "itp_expira"}
    optional_cols = {"marca", "asigurare_expira"}  # asigurarea devine complet opțională

    # normalizeaza header-ele doar pe case (litere mici/mari)
    rename_map = {}
    lc_cols = {c.lower(): c for c in df.columns}
    for col in list(required_cols | optional_cols):
        if col in lc_cols and lc_cols[col] != col:
            rename_map[lc_cols[col]] = col
    if rename_map:
        df = df.rename(columns=rename_map)

    missing_cols = required_cols - set(df.columns)
    if missing_cols:
        raise SystemExit(f"Lipsesc coloanele obligatorii: {', '.join(sorted(missing_cols))}")

    already_sent = read_sent_log()
    seen_keys_run = set()
    total_to_send = 0

    for _, row in df.iterrows():
        nr = str(row["nr_masina"]).strip().upper()
        marca = str(row["marca"]).strip() if "marca" in df.columns and pd.notna(row["marca"]) else ""
        prefix_marca = (marca + " ") if marca else ""

        # Construim lista de verificat DINAMIC, doar pentru coloanele existente
        date_fields = []
        if "rovinieta_expira" in df.columns:
            date_fields.append(("ROVINIETA", "rovinieta_expira"))
        if "itp_expira" in df.columns:
            date_fields.append(("ITP", "itp_expira"))
        if "asigurare_expira" in df.columns:
            date_fields.append(("ASIGURARE", "asigurare_expira"))

        for tip, col in date_fields:
            d = parse_date(row[col])
            if not d:
                continue

            days_left = (d - today).days

            # Trimite la praguri (inclusiv "azi") SAU zilnic dacă e depășit
            if (days_left in TRIGGERS) or (days_left < 0):
                key = (nr, tip, d.strftime(DATE_FORMAT_OUTPUT), str(days_left))

                if key in seen_keys_run:
                    logger.info("Skip (duplicat in aceeasi rulare): %s", key)
                    continue
                seen_keys_run.add(key)

                if key in already_sent:
                    logger.info("Skip (deja trimis anterior pentru %s)", key)
                    continue

                if days_left < 0:
                    subject, body = build_overdue_msg(tip, prefix_marca, nr, d, -days_left)
                elif days_left == 0:
                    subject, body = build_today_msg(tip, prefix_marca, nr, d)
                else:
                    subject, body = build_future_msg(tip, prefix_marca, nr, d, days_left)

                try:
                    send_mail(subject, body)
                    append_sent_log(nr, tip, d.strftime(DATE_FORMAT_OUTPUT), days_left)
                    logger.info("Trimis: %s", subject)
                    total_to_send += 1
                except Exception:
                    logger.exception("Eroare la trimitere pentru %s %s", nr, tip)

    logger.info("Rulare finalizata. Email-uri trimise: %s", total_to_send)

if __name__ == "__main__":
    main()
