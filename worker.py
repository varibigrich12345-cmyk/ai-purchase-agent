"""
Worker для обработки задач поиска автозапчастей.
Запускает ZZAP, STparts и Trast последовательно.
Версия: 3.1 - CDP клиенты + Trast

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
from trast_cdp_client import TrastCDPClient  # Stealth mode с обходом JS-challenge
from autovid_cdp_client import AutoVidCDPClient  # Auto-VID с WooCommerce
from autotrade_client import AutoTradeClient  # sklad.autotrade.su
from config import DB_PATH

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

DBPATH = DB_PATH

def get_db_connection():
    """Создать подключение к БД"""
    conn = sqlite3.connect(str(DBPATH))
    conn.row_factory = sqlite3.Row
    return conn

async def process_tasks():
    """
    Главный цикл обработки задач.
    Последовательно запускает ZZAP, STparts и Trast для каждой задачи.
    """
    logger.info("🔥 Worker запущен!")
    logger.info(f"📁 База данных: {DBPATH}")
    logger.info("🌐 Режим: CDP (подключение к Chrome)")
    logger.info("💡 Убедитесь, что Chrome запущен через start_chrome_debug.bat")

    # Подключаемся к Chrome через CDP
    logger.info("🔧 Подключение к Chrome CDP...")

    async with ZZapCDPClient() as zzap_client, STPartsCDPClient() as stparts_client, TrastCDPClient() as trast_client, AutoVidCDPClient() as autovid_client, AutoTradeClient() as autotrade_client:
        logger.info("  ✅ ZZAP клиент подключён")
        logger.info("  ✅ STparts клиент подключён")
        logger.info("  ✅ Trast клиент подключён (stealth режим)")
        logger.info("  ✅ AutoVID клиент подключён")
        logger.info("  ✅ AutoTrade клиент подключён")
        logger.info("✅ Все клиенты готовы к работе!")

        while True:
            conn = None
            task_id = None

            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, partnumber, search_brand FROM tasks WHERE status = 'PENDING' ORDER BY created_at ASC LIMIT 1"
                )

                task = cursor.fetchone()

                if task:
                    task_id, partnumber, search_brand = task['id'], task['partnumber'], task['search_brand']
                    logger.info(f"\n{'='*60}")
                    logger.info(f"📦 Обработка задачи #{task_id}: {partnumber}")
                    if search_brand:
                        logger.info(f"   🔍 Фильтр по бренду: {search_brand}")
                    logger.info(f"{'='*60}")

                    cursor.execute(
                        "UPDATE tasks SET status = 'RUNNING', started_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (task_id,)
                    )
                    conn.commit()

                    # Таймаут для каждого сайта (120 секунд)
                    SITE_TIMEOUT = 120

                    logger.info("🔵 [1/5] Поиск на ZZAP.ru...")
                    try:
                        zzap_result = await asyncio.wait_for(
                            zzap_client.search_part_with_retry(partnumber, brand_filter=search_brand, max_retries=2),
                            timeout=SITE_TIMEOUT
                        )
                    except asyncio.TimeoutError:
                        logger.error(f"  ⏱️ ZZAP: таймаут {SITE_TIMEOUT}с")
                        zzap_result = {'status': 'timeout', 'prices': None}

                    logger.info("🟢 [2/5] Поиск на STparts.ru...")
                    try:
                        stparts_result = await asyncio.wait_for(
                            stparts_client.search_part_with_retry(partnumber, brand_filter=search_brand, max_retries=2),
                            timeout=SITE_TIMEOUT
                        )
                    except asyncio.TimeoutError:
                        logger.error(f"  ⏱️ STparts: таймаут {SITE_TIMEOUT}с")
                        stparts_result = {'status': 'timeout', 'prices': None}

                    logger.info("🟠 [3/5] Поиск на Trast.ru (stealth)...")
                    try:
                        trast_result = await asyncio.wait_for(
                            trast_client.search_part_with_retry(partnumber, brand_filter=search_brand, max_retries=2),
                            timeout=SITE_TIMEOUT
                        )
                    except asyncio.TimeoutError:
                        logger.error(f"  ⏱️ Trast: таймаут {SITE_TIMEOUT}с")
                        trast_result = {'status': 'timeout', 'prices': None}

                    logger.info("🟣 [4/5] Поиск на Auto-VID.com...")
                    try:
                        autovid_result = await asyncio.wait_for(
                            autovid_client.search_part_with_retry(partnumber, brand_filter=search_brand, max_retries=2),
                            timeout=SITE_TIMEOUT
                        )
                    except asyncio.TimeoutError:
                        logger.error(f"  ⏱️ AutoVID: таймаут {SITE_TIMEOUT}с")
                        autovid_result = {'status': 'timeout', 'prices': None}

                    logger.info("🟤 [5/5] Поиск на AutoTrade.su...")
                    try:
                        autotrade_result = await asyncio.wait_for(
                            autotrade_client.search_part_with_retry(partnumber, brand_filter=search_brand, max_retries=2),
                            timeout=SITE_TIMEOUT
                        )
                    except asyncio.TimeoutError:
                        logger.error(f"  ⏱️ AutoTrade: таймаут {SITE_TIMEOUT}с")
                        autotrade_result = {'status': 'timeout', 'prices': None}

                    all_prices = []
                    zzap_min = None
                    stparts_min = None
                    trast_min = None
                    autovid_min = None
                    autotrade_min = None
                    brand = None

                    if zzap_result.get('status') in ['DONE', 'success'] and zzap_result.get('prices'):
                        zzap_min = zzap_result['prices'].get('min')
                        if zzap_min:
                            all_prices.append(zzap_min)
                            logger.info(f"  ✅ ZZAP: {zzap_min}₽")
                        # Получаем бренд из ZZAP
                        if not brand and zzap_result.get('brand'):
                            brand = zzap_result['brand']
                            logger.info(f"  🏷️ Бренд (ZZAP): {brand}")
                    else:
                        logger.warning(f"  ⚠️ ZZAP: {zzap_result.get('status', 'error')}")

                    if stparts_result.get('status') == 'success' and stparts_result.get('prices'):
                        stparts_min = stparts_result['prices'].get('min')
                        if stparts_min:
                            all_prices.append(stparts_min)
                            logger.info(f"  ✅ STparts: {stparts_min}₽")
                        # Получаем бренд из STparts если не нашли ранее
                        if not brand and stparts_result.get('brand'):
                            brand = stparts_result['brand']
                            logger.info(f"  🏷️ Бренд (STparts): {brand}")
                    else:
                        logger.warning(f"  ⚠️ STparts: {stparts_result.get('status', 'error')}")

                    if trast_result.get('status') == 'success' and trast_result.get('prices'):
                        trast_min = trast_result['prices'].get('min')
                        if trast_min:
                            all_prices.append(trast_min)
                            logger.info(f"  ✅ Trast: {trast_min}₽")
                        # Получаем бренд из Trast если не нашли ранее
                        if not brand and trast_result.get('brand'):
                            brand = trast_result['brand']
                            logger.info(f"  🏷️ Бренд (Trast): {brand}")
                    else:
                        logger.warning(f"  ⚠️ Trast: {trast_result.get('status', 'error')}")

                    if autovid_result.get('status') == 'success' and autovid_result.get('prices'):
                        autovid_min = autovid_result['prices'].get('min')
                        if autovid_min:
                            all_prices.append(autovid_min)
                            logger.info(f"  ✅ AutoVID: {autovid_min}₽")
                        # Получаем бренд из AutoVID если не нашли ранее
                        if not brand and autovid_result.get('brand'):
                            brand = autovid_result['brand']
                            logger.info(f"  🏷️ Бренд (AutoVID): {brand}")
                    else:
                        logger.warning(f"  ⚠️ AutoVID: {autovid_result.get('status', 'error')}")

                    if autotrade_result.get('status') in ['DONE', 'success'] and autotrade_result.get('prices'):
                        autotrade_min = autotrade_result['prices'].get('min')
                        if autotrade_min:
                            all_prices.append(autotrade_min)
                            logger.info(f"  ✅ AutoTrade: {autotrade_min}₽")
                        # Получаем бренд из AutoTrade если не нашли ранее
                        if not brand and autotrade_result.get('brand'):
                            brand = autotrade_result['brand']
                            logger.info(f"  🏷️ Бренд (AutoTrade): {brand}")
                    else:
                        logger.warning(f"  ⚠️ AutoTrade: {autotrade_result.get('status', 'error')}")

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
                                trast_min_price = ?,
                                autovid_min_price = ?,
                                autotrade_min_price = ?,
                                brand = ?,
                                result_url = ?,
                                completed_at = CURRENT_TIMESTAMP
                            WHERE id = ?""",
                            (
                                min_price,
                                avg_price,
                                zzap_min,
                                stparts_min,
                                trast_min,
                                autovid_min,
                                autotrade_min,
                                brand,
                                zzap_result.get('url') or stparts_result.get('url') or trast_result.get('url') or autovid_result.get('url') or autotrade_result.get('url'),
                                task_id
                            )
                        )

                        logger.info(f"\n🎉 Задача #{task_id} завершена!")
                        logger.info(f"   💰 Лучшая цена: {min_price}₽")
                        logger.info(f"   📊 Средняя: {avg_price}₽")
                        if brand:
                            logger.info(f"   🏷️ Бренд: {brand}")
                        if zzap_min:
                            logger.info(f"   🔵 ZZAP: {zzap_min}₽")
                        if stparts_min:
                            logger.info(f"   🟢 STparts: {stparts_min}₽")
                        if trast_min:
                            logger.info(f"   🟠 Trast: {trast_min}₽")
                        if autovid_min:
                            logger.info(f"   🟣 AutoVID: {autovid_min}₽")
                        if autotrade_min:
                            logger.info(f"   🟤 AutoTrade: {autotrade_min}₽")

                    else:
                        error_msg = f"ZZAP: {zzap_result.get('status')}, STparts: {stparts_result.get('status')}, Trast: {trast_result.get('status')}, AutoVID: {autovid_result.get('status')}, AutoTrade: {autotrade_result.get('status')}"
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
