import sqlite3

conn = sqlite3.connect('tasks.db')
cursor = conn.cursor()

try:
    cursor.execute("ALTER TABLE tasks ADD COLUMN zzap_min_price REAL")
    cursor.execute("ALTER TABLE tasks ADD COLUMN stparts_min_price REAL")
    conn.commit()
    print("✅ Миграция выполнена успешно!")
except Exception as e:
    print(f"❌ Ошибка: {e}")
    print("💡 Возможно, поля уже существуют - это нормально")
finally:
    conn.close()
