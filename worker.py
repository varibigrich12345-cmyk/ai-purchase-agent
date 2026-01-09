import asyncio
import sys
import logging
from pathlib import Path

BASEDIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASEDIR))

import sqlite3
from zzap_browser_client import ZZapBrowserClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DBPATH = BASEDIR / "tasks.db"

def get_db_connection():
    conn = sqlite3.connect(str(DBPATH))
    conn.row_factory = sqlite3.Row
    return conn

async def process_tasks():
    logger.info("🔥 Worker запущен!")
    
    # headless=False для отладки, измените на True для продакшена
    async with ZZapBrowserClient(headless=False) as client:
        while True:
            conn = None
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                
                cursor.execute(
                    "SELECT id, partnumber FROM tasks WHERE status = 'PENDING' ORDER BY created_at ASC LIMIT 1"
                )
                task = cursor.fetchone()
                
                if task:
                    task_id, partnumber = task['id'], task['partnumber']
                    logger.info(f"📦 Обработка задачи #{task_id}: {partnumber}")
                    
                    cursor.execute(
                        "UPDATE tasks SET status = 'RUNNING', started_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (task_id,)
                    )
                    conn.commit()
                    
                    # Выполнить поиск
                    result = await client.search_part_with_retry(partnumber, max_retries=2)
                    
                    # Сохранить результат
                    if result['status'] == 'DONE' and result['prices']:
                        cursor.execute(
                            """UPDATE tasks SET 
                            status = 'DONE',
                            min_price = ?,
                            avg_price = ?,
                            result_url = ?,
                            completed_at = CURRENT_TIMESTAMP
                            WHERE id = ?""",
                            (
                                result['prices']['min'],
                                result['prices']['avg'],
                                result['url'],
                                task_id
                            )
                        )
                        logger.info(f"✅ Задача #{task_id} завершена успешно!")
                    else:
                        cursor.execute(
                            """UPDATE tasks SET 
                            status = 'ERROR',
                            error_message = ?,
                            completed_at = CURRENT_TIMESTAMP
                            WHERE id = ?""",
                            (result.get('error', 'No prices found'), task_id)
                        )
                        logger.error(f"❌ Задача #{task_id} завершена с ошибкой")
                    
                    conn.commit()
                else:
                    await asyncio.sleep(2)
                    
            except Exception as e:
                logger.error(f"❌ Ошибка worker: {e}", exc_info=True)
                if 'task_id' in locals():
                    try:
                        if conn:
                            cursor = conn.cursor()
                            cursor.execute(
                                """UPDATE tasks SET 
                                status = 'ERROR',
                                error_message = ?,
                                completed_at = CURRENT_TIMESTAMP
                                WHERE id = ?""",
                                (str(e), task_id)
                            )
                            conn.commit()
                    except:
                        pass
                await asyncio.sleep(5)
            finally:
                if conn:
                    conn.close()

if __name__ == "__main__":
    try:
        asyncio.run(process_tasks())
    except KeyboardInterrupt:
        logger.info("👋 Worker остановлен")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}", exc_info=True)
