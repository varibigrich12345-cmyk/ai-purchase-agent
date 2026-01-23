"""
Worker для обработки задач поиска автозапчастей.
Запускает ZZAP, STparts и Trast последовательно.
Версия: 3.1 - CDP клиенты + Trast

Требования: Запустите start_chrome_debug.bat перед запуском worker.
"""

import asyncio
import sys
import logging
import time
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
    
    # Создаём клиенты
    zzap_client = ZZapCDPClient()
    stparts_client = STPartsCDPClient()
    trast_client = TrastCDPClient()
    autovid_client = AutoVidCDPClient()
    autotrade_client = AutoTradeClient()
    
    # Параллельная инициализация всех клиентов
    logger.info("🚀 Параллельная инициализация клиентов...")
    init_results = await asyncio.gather(
        zzap_client.connect(),
        stparts_client.connect(),
        trast_client.connect(),
        autovid_client.connect(),
        autotrade_client.connect(),
        return_exceptions=True
    )

    # Проверяем результаты инициализации
    clients_ok = True
    for i, (name, result) in enumerate([
        ("ZZAP", init_results[0]),
        ("STparts", init_results[1]),
        ("Trast", init_results[2]),
        ("AutoVID", init_results[3]),
        ("AutoTrade", init_results[4])
    ]):
        if isinstance(result, Exception):
            logger.error(f"  ❌ {name} клиент: ошибка подключения {result}")
            clients_ok = False
        elif result:
            logger.info(f"  ✅ {name} клиент подключён")
        else:
            logger.error(f"  ❌ {name} клиент: подключение не удалось")
            clients_ok = False
    
    if not clients_ok:
        logger.error("❌ Не все клиенты подключены, завершение работы")
        return
    
    logger.info("✅ Все клиенты готовы к работе!")
    
    try:

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
                    
                    # Засекаем время начала задачи
                    start_total = time.time()
                    print(f"[TIMING] Начало задачи: {partnumber} {search_brand or '(без бренда)'}")
                    
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

                    # Таймаут для каждого сайта (30 секунд)
                    SITE_TIMEOUT = 30
                    print(f"[TIMING] Таймаут установлен: {SITE_TIMEOUT} сек")
                    print(f"[TIMING] Режим выполнения: ПАРАЛЛЕЛЬНО (asyncio.gather)")
                    print(f"[TIMING] Кэширование: ВКЛЮЧЕНО (30 минут)")

                    # Проверяем кэш перед парсингом (используем одно подключение для чтения)
                    cache_conn_read = get_db_connection()
                    cache_cursor_read = cache_conn_read.cursor()
                    
                    def check_cache(source_name, cache_key_brand):
                        """Проверить кэш для источника."""
                        cache_cursor_read.execute(
                            """
                            SELECT price, url FROM price_cache
                            WHERE partnumber = ? AND (? IS NULL OR brand = ?) AND source = ?
                            AND datetime(cached_at) > datetime('now', '-30 minutes')
                            ORDER BY cached_at DESC
                            LIMIT 1
                            """,
                            (partnumber, cache_key_brand, cache_key_brand, source_name)
                        )
                        return cache_cursor_read.fetchone()
                    
                    # Проверяем кэш для всех источников
                    zzap_cache = check_cache("zzap", search_brand)
                    stparts_cache = check_cache("stparts", search_brand)
                    trast_cache = check_cache("trast", search_brand)
                    autovid_cache = check_cache("autovid", search_brand)
                    autotrade_cache = check_cache("autotrade", search_brand)
                    
                    cache_conn_read.close()
                    
                    # Функции для парсинга с проверкой кэша
                    async def parse_zzap():
                        start_time = time.time()
                        if zzap_cache:
                            elapsed = time.time() - start_time
                            logger.info(f"  ✅ zzap: результат из кэша (цена: {zzap_cache['price']}₽)")
                            print(f"[TIMING] ZZAP: {elapsed:.1f} сек (ИЗ КЭША)")
                            return {
                                'status': 'success',
                                'prices': {'min': zzap_cache['price'], 'avg': zzap_cache['price']},
                                'url': zzap_cache['url'],
                                'from_cache': True,
                                'elapsed_time': elapsed
                            }
                        print(f"[TIMING] ZZAP: начало парсинга...")
                        result = await zzap_client.search_part_with_retry(partnumber, brand_filter=search_brand, max_retries=2)
                        elapsed = time.time() - start_time
                        if result.get('prices') and result['prices'].get('min'):
                            cache_conn = get_db_connection()
                            cache_cursor = cache_conn.cursor()
                            cache_cursor.execute(
                                "INSERT INTO price_cache (partnumber, brand, source, price, url) VALUES (?, ?, ?, ?, ?)",
                                (partnumber, search_brand, "zzap", result['prices']['min'], result.get('url'))
                            )
                            cache_conn.commit()
                            cache_conn.close()
                        result['elapsed_time'] = elapsed
                        result['from_cache'] = False
                        print(f"[TIMING] ZZAP: {elapsed:.1f} сек (ПАРСИНГ)")
                        return result
                    
                    async def parse_stparts():
                        start_time = time.time()
                        if stparts_cache:
                            elapsed = time.time() - start_time
                            logger.info(f"  ✅ stparts: результат из кэша (цена: {stparts_cache['price']}₽)")
                            print(f"[TIMING] STparts: {elapsed:.1f} сек (ИЗ КЭША)")
                            return {
                                'status': 'success',
                                'prices': {'min': stparts_cache['price'], 'avg': stparts_cache['price']},
                                'url': stparts_cache['url'],
                                'from_cache': True,
                                'elapsed_time': elapsed
                            }
                        print(f"[TIMING] STparts: начало парсинга...")
                        result = await stparts_client.search_part_with_retry(partnumber, brand_filter=search_brand, max_retries=2)
                        elapsed = time.time() - start_time
                        if result.get('prices') and result['prices'].get('min'):
                            cache_conn = get_db_connection()
                            cache_cursor = cache_conn.cursor()
                            cache_cursor.execute(
                                "INSERT INTO price_cache (partnumber, brand, source, price, url) VALUES (?, ?, ?, ?, ?)",
                                (partnumber, search_brand, "stparts", result['prices']['min'], result.get('url'))
                            )
                            cache_conn.commit()
                            cache_conn.close()
                        result['elapsed_time'] = elapsed
                        result['from_cache'] = False
                        print(f"[TIMING] STparts: {elapsed:.1f} сек (ПАРСИНГ)")
                        return result

                    async def parse_trast():
                        start_time = time.time()
                        if trast_cache:
                            elapsed = time.time() - start_time
                            logger.info(f"  ✅ trast: результат из кэша (цена: {trast_cache['price']}₽)")
                            print(f"[TIMING] Trast: {elapsed:.1f} сек (ИЗ КЭША)")
                            return {
                                'status': 'success',
                                'prices': {'min': trast_cache['price'], 'avg': trast_cache['price']},
                                'url': trast_cache['url'],
                                'from_cache': True,
                                'elapsed_time': elapsed
                            }
                        print(f"[TIMING] Trast: начало парсинга...")
                        result = await trast_client.search_part_with_retry(partnumber, brand_filter=search_brand, max_retries=2)
                        elapsed = time.time() - start_time
                        if result.get('prices') and result['prices'].get('min'):
                            cache_conn = get_db_connection()
                            cache_cursor = cache_conn.cursor()
                            cache_cursor.execute(
                                "INSERT INTO price_cache (partnumber, brand, source, price, url) VALUES (?, ?, ?, ?, ?)",
                                (partnumber, search_brand, "trast", result['prices']['min'], result.get('url'))
                            )
                            cache_conn.commit()
                            cache_conn.close()
                        result['elapsed_time'] = elapsed
                        result['from_cache'] = False
                        print(f"[TIMING] Trast: {elapsed:.1f} сек (ПАРСИНГ)")
                        return result
                    
                    async def parse_autovid():
                        start_time = time.time()
                        if autovid_cache:
                            elapsed = time.time() - start_time
                            logger.info(f"  ✅ autovid: результат из кэша (цена: {autovid_cache['price']}₽)")
                            print(f"[TIMING] AutoVID: {elapsed:.1f} сек (ИЗ КЭША)")
                            return {
                                'status': 'success',
                                'prices': {'min': autovid_cache['price'], 'avg': autovid_cache['price']},
                                'url': autovid_cache['url'],
                                'from_cache': True,
                                'elapsed_time': elapsed
                            }
                        print(f"[TIMING] AutoVID: начало парсинга...")
                        result = await autovid_client.search_part_with_retry(partnumber, brand_filter=search_brand, max_retries=2)
                        elapsed = time.time() - start_time
                        if result.get('prices') and result['prices'].get('min'):
                            cache_conn = get_db_connection()
                            cache_cursor = cache_conn.cursor()
                            cache_cursor.execute(
                                "INSERT INTO price_cache (partnumber, brand, source, price, url) VALUES (?, ?, ?, ?, ?)",
                                (partnumber, search_brand, "autovid", result['prices']['min'], result.get('url'))
                            )
                            cache_conn.commit()
                            cache_conn.close()
                        result['elapsed_time'] = elapsed
                        result['from_cache'] = False
                        print(f"[TIMING] AutoVID: {elapsed:.1f} сек (ПАРСИНГ)")
                        return result
                    
                    async def parse_autotrade():
                        start_time = time.time()
                        if autotrade_cache:
                            elapsed = time.time() - start_time
                            logger.info(f"  ✅ autotrade: результат из кэша (цена: {autotrade_cache['price']}₽)")
                            print(f"[TIMING] AutoTrade: {elapsed:.1f} сек (ИЗ КЭША)")
                            return {
                                'status': 'success',
                                'prices': {'min': autotrade_cache['price'], 'avg': autotrade_cache['price']},
                                'url': autotrade_cache['url'],
                                'from_cache': True,
                                'elapsed_time': elapsed
                            }
                        print(f"[TIMING] AutoTrade: начало парсинга...")
                        result = await autotrade_client.search_part_with_retry(partnumber, brand_filter=search_brand, max_retries=2)
                        elapsed = time.time() - start_time
                        if result.get('prices') and result['prices'].get('min'):
                            cache_conn = get_db_connection()
                            cache_cursor = cache_conn.cursor()
                            cache_cursor.execute(
                                "INSERT INTO price_cache (partnumber, brand, source, price, url) VALUES (?, ?, ?, ?, ?)",
                                (partnumber, search_brand, "autotrade", result['prices']['min'], result.get('url'))
                            )
                            cache_conn.commit()
                            cache_conn.close()
                        result['elapsed_time'] = elapsed
                        result['from_cache'] = False
                        print(f"[TIMING] AutoTrade: {elapsed:.1f} сек (ПАРСИНГ)")
                        return result

                    # Параллельный запуск всех парсеров
                    logger.info("🚀 Запуск ПАРАЛЛЕЛЬНОГО поиска на всех 5 сайтах...")
                    start_parallel = time.time()

                    # ПРОВЕРКА: Используется ли asyncio.gather()?
                    print(f"[TIMING] Используется asyncio.gather(): ДА")
                    print(f"[TIMING] Парсеры запускаются: ПАРАЛЛЕЛЬНО")

                    # Параллельный запуск всех парсеров с явным таймаутом
                    results = await asyncio.gather(
                        asyncio.wait_for(parse_zzap(), timeout=SITE_TIMEOUT),
                        asyncio.wait_for(parse_stparts(), timeout=SITE_TIMEOUT),
                        asyncio.wait_for(parse_trast(), timeout=SITE_TIMEOUT),
                        asyncio.wait_for(parse_autovid(), timeout=SITE_TIMEOUT),
                        asyncio.wait_for(parse_autotrade(), timeout=SITE_TIMEOUT),
                        return_exceptions=True
                    )

                    zzap_result, stparts_result, trast_result, autovid_result, autotrade_result = results
                    
                    parallel_elapsed = time.time() - start_parallel
                    print(f"[TIMING] Параллельное выполнение завершено за: {parallel_elapsed:.1f} сек")
                    
                    # Обрабатываем исключения и таймауты
                    parser_names = ["ZZAP", "STparts", "Trast", "AutoVID", "AutoTrade"]
                    for i, (name, result) in enumerate(zip(parser_names, results)):
                        if isinstance(result, Exception):
                            if isinstance(result, asyncio.TimeoutError):
                                logger.warning(f"⏱️ {name} таймаут: {result}")
                                print(f"[TIMEOUT] Парсер {name} не ответил за {SITE_TIMEOUT} сек")
                                if i == 0:
                                    zzap_result = {'status': 'timeout', 'prices': None, 'elapsed_time': SITE_TIMEOUT, 'from_cache': False}
                                elif i == 1:
                                    stparts_result = {'status': 'timeout', 'prices': None, 'elapsed_time': SITE_TIMEOUT, 'from_cache': False}
                                elif i == 2:
                                    trast_result = {'status': 'timeout', 'prices': None, 'elapsed_time': SITE_TIMEOUT, 'from_cache': False}
                                elif i == 3:
                                    autovid_result = {'status': 'timeout', 'prices': None, 'elapsed_time': SITE_TIMEOUT, 'from_cache': False}
                                elif i == 4:
                                    autotrade_result = {'status': 'timeout', 'prices': None, 'elapsed_time': SITE_TIMEOUT, 'from_cache': False}
                            else:
                                logger.error(f"  ❌ {name}: исключение {result}")
                                print(f"[ERROR] Парсер {name}: {result}")
                                if i == 0:
                                    zzap_result = {'status': 'error', 'prices': None, 'elapsed_time': 0, 'from_cache': False}
                                elif i == 1:
                                    stparts_result = {'status': 'error', 'prices': None, 'elapsed_time': 0, 'from_cache': False}
                                elif i == 2:
                                    trast_result = {'status': 'error', 'prices': None, 'elapsed_time': 0, 'from_cache': False}
                                elif i == 3:
                                    autovid_result = {'status': 'error', 'prices': None, 'elapsed_time': 0, 'from_cache': False}
                                elif i == 4:
                                    autotrade_result = {'status': 'error', 'prices': None, 'elapsed_time': 0, 'from_cache': False}
                    
                    logger.info("✅ Параллельный поиск завершён!")

                    # Выводим детальное время каждого парсера
                    print(f"[TIMING] ZZAP: {zzap_result.get('elapsed_time', 0):.1f} сек {'(КЭШ)' if zzap_result.get('from_cache') else '(ПАРСИНГ)'}")
                    print(f"[TIMING] STparts: {stparts_result.get('elapsed_time', 0):.1f} сек {'(КЭШ)' if stparts_result.get('from_cache') else '(ПАРСИНГ)'}")
                    print(f"[TIMING] Trast: {trast_result.get('elapsed_time', 0):.1f} сек {'(КЭШ)' if trast_result.get('from_cache') else '(ПАРСИНГ)'}")
                    print(f"[TIMING] AutoVID: {autovid_result.get('elapsed_time', 0):.1f} сек {'(КЭШ)' if autovid_result.get('from_cache') else '(ПАРСИНГ)'}")
                    print(f"[TIMING] AutoTrade: {autotrade_result.get('elapsed_time', 0):.1f} сек {'(КЭШ)' if autotrade_result.get('from_cache') else '(ПАРСИНГ)'}")

                    all_prices = []
                    zzap_min = None
                    stparts_min = None
                    trast_min = None
                    autovid_min = None
                    autotrade_min = None
                    brand = None

                    def save_price_history(cur, partnumber_value, brand_value, source, price_value):
                        """
                        Сохраняем цену в price_history, если за сегодня по этому источнику
                        ещё не было записи с такой же ценой.
                        """
                        if not price_value:
                            return
                        cur.execute(
                            """
                            SELECT 1 FROM price_history
                            WHERE partnumber = ?
                              AND (? IS NULL OR brand = ?)
                              AND source = ?
                              AND price = ?
                              AND date(recorded_at) = date('now')
                            LIMIT 1
                            """,
                            (partnumber_value, brand_value, brand_value, source, price_value),
                        )
                        if cur.fetchone():
                            return

                        cur.execute(
                            """
                            INSERT INTO price_history (partnumber, brand, source, price)
                            VALUES (?, ?, ?, ?)
                            """,
                            (partnumber_value, brand_value, source, price_value),
                        )

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

                    # После того как определён бренд (если он нашёлся), сохраняем историю цен
                    try:
                        save_price_history(cursor, partnumber, brand, "zzap", zzap_min)
                        save_price_history(cursor, partnumber, brand, "stparts", stparts_min)
                        save_price_history(cursor, partnumber, brand, "trast", trast_min)
                        save_price_history(cursor, partnumber, brand, "autovid", autovid_min)
                        save_price_history(cursor, partnumber, brand, "autotrade", autotrade_min)
                    except Exception as e:
                        logger.error(f"⚠️ Ошибка сохранения истории цен: {e}", exc_info=True)

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

                    # Итоговое логирование времени
                    total_elapsed = time.time() - start_total
                    from_cache_count = sum([
                        1 if zzap_result.get('from_cache') else 0,
                        1 if stparts_result.get('from_cache') else 0,
                        1 if trast_result.get('from_cache') else 0,
                        1 if autovid_result.get('from_cache') else 0,
                        1 if autotrade_result.get('from_cache') else 0,
                    ])
                    parsed_count = 5 - from_cache_count

                    print(f"\n[TIMING] {'='*60}")
                    print(f"[TIMING] ИТОГО: {total_elapsed:.1f} сек")
                    print(f"[TIMING] Из кэша: {from_cache_count}/5 парсеров")
                    print(f"[TIMING] Парсинг: {parsed_count}/5 парсеров")
                    print(f"[TIMING] Параллельно: ДА (asyncio.gather)")
                    print(f"[TIMING] Проверка кэша: ДА (перед каждым парсером)")
                    print(f"[TIMING] Таймаут: {SITE_TIMEOUT} сек (на каждый парсер)")
                    print(f"[TIMING] {'='*60}\n")

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
    
    # Закрываем все клиенты
    finally:
        logger.info("🔌 Закрытие всех клиентов...")
        await asyncio.gather(
            zzap_client.disconnect() if hasattr(zzap_client, 'disconnect') else asyncio.sleep(0),
            stparts_client.disconnect() if hasattr(stparts_client, 'disconnect') else asyncio.sleep(0),
            trast_client.disconnect() if hasattr(trast_client, 'disconnect') else asyncio.sleep(0),
            autovid_client.disconnect() if hasattr(autovid_client, 'disconnect') else asyncio.sleep(0),
            autotrade_client.disconnect() if hasattr(autotrade_client, 'disconnect') else asyncio.sleep(0),
            return_exceptions=True
        )
        logger.info("✅ Все клиенты закрыты")

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
