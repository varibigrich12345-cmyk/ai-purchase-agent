# config.py
import os
from pathlib import Path

BASEDIR = Path(__file__).resolve().parent

# stparts.ru credentials
STPARTS_LOGIN = os.getenv("STPARTS_LOGIN", "89297748866@mail.ru")
STPARTS_PASSWORD = os.getenv("STPARTS_PASSWORD", "SSSsss@12345678")

# trast.ru credentials
TRAST_LOGIN = os.getenv("TRAST_LOGIN", "")
TRAST_PASSWORD = os.getenv("TRAST_PASSWORD", "")

# auto-vid.com credentials
AUTOVID_LOGIN = os.getenv("AUTOVID_LOGIN", "danik.servis@mail.ru")
AUTOVID_PASSWORD = os.getenv("AUTOVID_PASSWORD", "AAAAaaaa@12345678")

# sklad.autotrade.su credentials
AUTOTRADE_EMAIL = os.getenv("AUTOTRADE_EMAIL", "")
AUTOTRADE_PASSWORD = os.getenv("AUTOTRADE_PASSWORD", "")

# Database - use env var for Docker, fallback to local for development
DB_PATH = Path(os.getenv("DATABASE_PATH", str(BASEDIR / "tasks.db")))

# Parser settings
ZZAP_MIN_PRICE = 2000
ZZAP_MAX_PRICE = 50000
STPARTS_MIN_PRICE = 2000
STPARTS_MAX_PRICE = 50000

# Chrome CDP settings
CHROME_CDP_ENDPOINT = os.getenv("CHROME_CDP_ENDPOINT", "http://localhost:9222")
COOKIES_BACKUP_DIR = BASEDIR / "cookies_backup"

# Keep-alive interval (seconds)
KEEP_ALIVE_INTERVAL = 20 * 60  # 20 minutes
