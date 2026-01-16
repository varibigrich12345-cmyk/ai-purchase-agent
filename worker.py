"""
Worker для обработки задач поиска автозапчастей.
Запускает ZZAP и STparts последовательно.
Версия: 3.0 - CDP клиенты (подключение к Chrome через remote debugging)

Требования: Запустите start_chrome_debug.bat перед запуском worker.
"""

import asyncio
import sys
import logging
from pathlib import Path

# Fix encoding for Windows console
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

BASEDIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASEDIR))

import sqlite3
from zzap_cdp_client import ZZapCDPClient
from stparts_cdp_client import STPartsCDPClient

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
    logger.info("🌐 Режим: CDP (подключение к Chrome)")
    logger.info("💡 Убедитесь, что Chrome запущен через start_chrome_debug.bat")

    # Подключаемся к Chrome через CDP
    logger.info("🔧 Подключение к Chrome CDP...")

    async with ZZapCDPClient() as zzap_client, STPartsCDPClient() as stparts_client:
        logger.info("  ✅ ZZAP клиент подключён")
        logger.info("  ✅ STparts клиент подключён")
        logger.info("✅ Оба клиента готовы к работе!")

        while True:
            conn = None
            task_id = None

            try:
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

                    cursor.execute(
                        "UPDATE tasks SET status = 'RUNNING', started_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (task_id,)
                    )
                    conn.commit()

                    logger.info("🔵 [1/2] Поиск на ZZAP.ru...")
                    zzap_result = await zzap_client.search_part_with_retry(partnumber, max_retries=2)

                    logger.info("🟢 [2/2] Поиск на STparts.ru...")
                    stparts_result = await stparts_client.search_part_with_retry(partnumber, max_retries=2)

                    all_prices = []
                    zzap_min = None
                    stparts_min = None

                    if zzap_result.get('status') in ['DONE', 'success'] and zzap_result.get('prices'):
                        zzap_min = zzap_result['prices'].get('min')
                        if zzap_min:
                            all_prices.append(zzap_min)
                            logger.info(f"  ✅ ZZAP: {zzap_min}₽")
                    else:
                        logger.warning(f"  ⚠️ ZZAP: {zzap_result.get('status', 'error')}")

                    if stparts_result.get('status') == 'success' and stparts_result.get('prices'):
                        stparts_min = stparts_result['prices'].get('min')
                        if stparts_min:
                            all_prices.append(stparts_min)
                            logger.info(f"  ✅ STparts: {stparts_min}₽")
                    else:
                        logger.warning(f"  ⚠️ STparts: {stparts_result.get('status', 'error')}")

                    if all_prices:
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
                        if zzap_min:
                            logger.info(f"   🔵 ZZAP: {zzap_min}₽")
                        if stparts_min:
                            logger.info(f"   🟢 STparts: {stparts_min}₽")

                    else:
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
                    logger.debug("💤 Нет задач, ожидание...")
                    await asyncio.sleep(2)

            except Exception as e:
                logger.error(f"❌ Ошибка worker: {e}", exc_info=True)

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
        print("="*70)
        print("  🚀 AI PURCHASE AGENT - Worker (CDP)")
        print("="*70)
        print("  📋 Режим: CDP (подключение к Chrome)")
        print("  💡 Запустите start_chrome_debug.bat перед запуском!")
        print("  🛑 Остановка: Ctrl+C")
        print("="*70)
        print()
        asyncio.run(process_tasks())
    except KeyboardInterrupt:
        print("\n" + "="*70)
        print("  👋 Worker остановлен пользователем")
        print("="*70)
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}", exc_info=True)
