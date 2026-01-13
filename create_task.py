import sqlite3

conn = sqlite3.connect('tasks.db')
conn.execute('INSERT INTO tasks (partnumber, status) VALUES (?, ?)', ('1920QK', 'PENDING'))
conn.commit()
print('✅ Задача создана: 1920QK')
conn.close()
