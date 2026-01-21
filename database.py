import sqlite3
from pathlib import Path
from typing import Optional, Dict, Any, List

# Путь к БД в корне проекта
DBPATH = Path(__file__).resolve().parent / "tasks.db"


def get_db_connection():
    """Создать подключение к БД"""
    conn = sqlite3.connect(str(DBPATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Инициализировать базу данных"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            partnumber TEXT NOT NULL,
            search_brand TEXT,
            status TEXT NOT NULL DEFAULT 'PENDING',
            min_price REAL,
            avg_price REAL,
            zzap_min_price REAL,
            stparts_min_price REAL,
            trast_min_price REAL,
            autovid_min_price REAL,
            autotrade_min_price REAL,
            brand TEXT,
            result_url TEXT,
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            started_at TIMESTAMP,
            completed_at TIMESTAMP
        )
    """)

    # Миграция: добавляем новые колонки если их нет
    new_columns = [
        'search_brand TEXT',
        'zzap_min_price REAL',
        'stparts_min_price REAL',
        'trast_min_price REAL',
        'autovid_min_price REAL',
        'autotrade_min_price REAL',
        'brand TEXT',
    ]
    for col_def in new_columns:
        col_name = col_def.split()[0]
        try:
            cursor.execute(f"ALTER TABLE tasks ADD COLUMN {col_def}")
        except:
            pass  # Колонка уже существует

    conn.commit()
    conn.close()


# Инициализация БД при импорте
init_db()
