import os
import csv
import smtplib
from datetime import date, datetime
from email.message import EmailMessage
import logging
from logging.handlers import RotatingFileHandler

import pandas as pd
from dateutil import parser as dateparser

# ------------------- Config -------------------
# Fisier local fallback (daca nu exista GSHEET_CSV_URL)
CSV_FILE = "camioane.csv"
# URL public CSV de la Google Sheets (File -> Share -> Publish to web -> CSV)
GSHEET_CSV_URL = os.getenv("GSHEET_CSV_URL", "").strip()

SENT_LOG = "sent_log.csv"          # pentru a evita dublurile in aceeasi rulare
TRIGGERS = {30, 15, 7, 4, 1}       # zile inainte de expirare pentru trimitere
DATE_FORMAT_OUTPUT = "%Y-%m-%d"    # cum afisam/trimitem datele

# SMTP din variabile de mediu (vin din GitHub Secrets pe Actions)
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
                row.get("nr_masina",""),
                row.get("tip",""),
                row.get("data_expirarii",""),
                row.get("days_left",""),
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

def load_fleet_df() -> pd.DataFrame:
    if GSHEET_CSV_URL:
        source = _cache_bust_url(GSHEET_CSV_URL)
        logger.info("Incarc datele din Google Sheets CSV (GSHEET_CSV_URL).")
        df = pd.read_csv(source, dtype=str, encoding="utf-8", sep=None, engine="python")
    else:
        if not os.path.exists(CSV_FILE):
            raise SystemExit(
                f"Nu gasesc {CSV_FILE} si nu ai setat GSHEET_CSV_URL. "
                "Seteaza GSHEET_CSV_URL sau adauga camioane.csv."
            )
        logger.info("Incarc datele din fisierul local: %s", CSV_FILE)
        df = pd.read_csv(CSV_FILE, dtype=str, encoding="utf-8", sep=None, engine="python")
    if not df.empty:
        df = df.dropna(how="all")
    return df

# ------------------- Core -------------------
def main():
    ensure_env()
    today = date.today()
    df = load_fleet_df()

    required_cols = {"nr_masina","rovinieta_expira","itp_expira","asigurare_expira"}
    optional_cols = {"marca"}

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
    total_to_send = 0

    for _, row in df.iterrows():
        nr = str(row["nr_masina"]).strip()
        marca = str(row["marca"]).strip() if "marca" in df.columns and pd.notna(row["marca"]) else ""
        prefix_marca = (marca + " ") if marca else ""

        dates = {
            "rovinieta": parse_date(row["rovinieta_expira"]),
            "itp": parse_date(row["itp_expira"]),
            "asigurare": parse_date(row["asigurare_expira"]),
        }
        for tip, d in dates.items():
            if not d:
                continue
            days_left = (d - today).days
            if days_left in TRIGGERS:
                key = (nr, tip, d.strftime(DATE_FORMAT_OUTPUT), str(days_left))
                if key in already_sent:
                    logger.info("Skip (deja trimis): %s %s %s (%s zile)", nr, tip, d, days_left)
                    continue

                subject = f"Expira {tip} la {prefix_marca}{nr} in {days_left} zile"
                body = (
                    f"Avertizare expirare: {tip}\n"
                    f"Masina: {prefix_marca}{nr}\n"
                    f"Data expirarii: {d.strftime(DATE_FORMAT_OUTPUT)}\n"
                    f"Au ramas: {days_left} zile\n\n"
                    f"Acest mesaj a fost generat automat."
                )

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
