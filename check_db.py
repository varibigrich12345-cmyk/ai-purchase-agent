import sqlite3

conn = sqlite3.connect('tasks.db')
cursor = conn.cursor()

cursor.execute("PRAGMA table_info(tasks)")
columns = cursor.fetchall()

print("📋 Структура таблицы tasks:")
print("="*60)
for col in columns:
    col_id, name, col_type, not_null, default, pk = col
    print(f"{col_id:2}. {name:20} {col_type:10} {'PK' if pk else ''}")

conn.close()
