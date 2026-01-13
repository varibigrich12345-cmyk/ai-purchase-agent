"""
Worker для обработки задач поиска автозапчастей.
Запускает ZZAP и STparts последовательно.
"""

import asyncio
import sys
import logging
from pathlib import Path

BASEDIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASEDIR))

import sqlite3
from playwright.async_api import async_playwright
from zzap_browser_client import ZZapBrowserClient
from stparts_browser_client import STPartsBrowserClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

DBPATH = BASEDIR / "tasks.db"

def get_db_connection():
    """Создать подключение к БД"""
    conn = sqlite3.connect(str(DBPATH))
    conn.row_factory = sqlite3.Row
    return conn

async def process_tasks():
    """
    Главный цикл обработки задач.
    Последовательно запускает ZZAP и STparts для каждой задачи.
    """
    logger.info("🔥 Worker запущен!")
    
    # Инициализируем Playwright один раз
    async with async_playwright() as pw:
        # Создаем клиенты для обоих сайтов
        # headless=False для отладки, измените на True для продакшена
        zzap_client = ZZapBrowserClient(headless=False)
        stparts_client = STPartsBrowserClient(pw, headless=False)
        
        # Запускаем оба клиента (контекстные менеджеры)
        async with zzap_client, stparts_client:
            logger.info("✅ Оба браузера готовы к работе!")
            
            while True:
                conn = None
                task_id = None
                
                try:
                    # Получаем следующую задачу
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT id, partnumber FROM tasks WHERE status = 'PENDING' ORDER BY created_at ASC LIMIT 1"
                    )
                    
                    task = cursor.fetchone()
                    
                    if task:
                        task_id, partnumber = task['id'], task['partnumber']
                        logger.info(f"\n{'='*60}")
                        logger.info(f"📦 Обработка задачи #{task_id}: {partnumber}")
                        logger.info(f"{'='*60}")
                        
                        # Обновляем статус на RUNNING
                        cursor.execute(
                            "UPDATE tasks SET status = 'RUNNING', started_at = CURRENT_TIMESTAMP WHERE id = ?",
                            (task_id,)
                        )
                        conn.commit()
                        
                        # ===== ПОСЛЕДОВАТЕЛЬНЫЙ ПОИСК =====
                        
                        # 1. ZZAP.ru
                        logger.info("🔵 [1/2] Поиск на ZZAP.ru...")
                        zzap_result = await zzap_client.search_part_with_retry(partnumber, max_retries=2)
                        
                        # 2. STparts.ru
                        logger.info("🟢 [2/2] Поиск на STparts.ru...")
                        stparts_result = await stparts_client.search_part_with_retry(partnumber, max_retries=2)
                        
                        # ===== АГРЕГАЦИЯ РЕЗУЛЬТАТОВ =====
                        
                        all_prices = []
                        zzap_min = None
                        stparts_min = None
                        
                        # Собираем цены с ZZAP
                        if zzap_result.get('status') in ['DONE', 'success'] and zzap_result.get('prices'):
                            zzap_min = zzap_result['prices'].get('min')
                            if zzap_min:
                                all_prices.append(zzap_min)
                                logger.info(f"  ✅ ZZAP: {zzap_min}₽")
                        else:
                            logger.warning(f"  ⚠️ ZZAP: {zzap_result.get('status', 'error')}")
                        
                        # Собираем цены с STparts
                        if stparts_result.get('status') == 'success' and stparts_result.get('prices'):
                            stparts_min = stparts_result['prices'].get('min')
                            if stparts_min:
                                all_prices.append(stparts_min)
                                logger.info(f"  ✅ STparts: {stparts_min}₽")
                        else:
                            logger.warning(f"  ⚠️ STparts: {stparts_result.get('status', 'error')}")
                        
                        # ===== СОХРАНЕНИЕ РЕЗУЛЬТАТОВ =====
                        
                        if all_prices:
                            # Есть хотя бы одна цена
                            min_price = min(all_prices)
                            avg_price = round(sum(all_prices) / len(all_prices), 2)
                            
                            cursor.execute(
                                """UPDATE tasks SET
                                    status = 'DONE',
                                    min_price = ?,
                                    avg_price = ?,
                                    zzap_min_price = ?,
                                    stparts_min_price = ?,
                                    result_url = ?,
                                    completed_at = CURRENT_TIMESTAMP
                                WHERE id = ?""",
                                (
                                    min_price,
                                    avg_price,
                                    zzap_min,
                                    stparts_min,
                                    zzap_result.get('url') or stparts_result.get('url'),
                                    task_id
                                )
                            )
                            
                            logger.info(f"\n🎉 Задача #{task_id} завершена!")
                            logger.info(f"   💰 Лучшая цена: {min_price}₽")
                            logger.info(f"   📊 Средняя: {avg_price}₽")
                            
                        else:
                            # Нет ни одной цены
                            error_msg = f"ZZAP: {zzap_result.get('status')}, STparts: {stparts_result.get('status')}"
                            cursor.execute(
                                """UPDATE tasks SET
                                    status = 'ERROR',
                                    error_message = ?,
                                    completed_at = CURRENT_TIMESTAMP
                                WHERE id = ?""",
                                (error_msg, task_id)
                            )
                            logger.error(f"❌ Задача #{task_id}: цены не найдены")
                        
                        conn.commit()
                        
                    else:
                        # Нет задач - ждём
                        logger.debug("💤 Нет задач, ожидание...")
                        await asyncio.sleep(2)
                
                except Exception as e:
                    logger.error(f"❌ Ошибка worker: {e}", exc_info=True)
                    
                    # Пытаемся отметить задачу как ERROR
                    if task_id and conn:
                        try:
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
        logger.info("\n👋 Worker остановлен пользователем")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}", exc_info=True)
