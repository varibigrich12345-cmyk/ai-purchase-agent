# config.py
import os
from pathlib import Path

BASEDIR = Path(__file__).resolve().parent

# stparts.ru credentials
STPARTS_LOGIN = os.getenv("STPARTS_LOGIN", "ваш_логин")
STPARTS_PASSWORD = os.getenv("STPARTS_PASSWORD", "ваш_пароль")

# Database
DB_PATH = BASEDIR / "tasks.db"

# Parser settings
ZZAP_MIN_PRICE = 2000
ZZAP_MAX_PRICE = 50000
STPARTS_MIN_PRICE = 2000
STPARTS_MAX_PRICE = 50000
