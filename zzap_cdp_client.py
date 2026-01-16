"""
CDP клиент для zzap.ru - подключается к уже запущенному Chrome.

Использование:
1. Запустите start_chrome_debug.bat
2. async with ZZapCDPClient() as client:
       result = await client.search_part("12345")
"""

import asyncio
import logging
import re
from typing import Dict, Any, List

from playwright.async_api import TimeoutError as PlaywrightTimeout

from base_browser_client import BaseBrowserClient

logger = logging.getLogger(__name__)


class ZZapCDPClient(BaseBrowserClient):
    """CDP клиент для zzap.ru с keep-alive."""

    SITE_NAME = "zzap"
    BASE_URL = "https://www.zzap.ru"

    async def check_auth(self) -> bool:
        """
        Проверить авторизацию на zzap.ru.
        ZZAP не требует авторизации для поиска, всегда возвращаем True.
        """
        return True

    async def auto_login(self) -> bool:
        """
        Автологин для zzap.ru.
        Не требуется - сайт работает без авторизации.
        """
        return True

    async def keep_alive(self) -> None:
        """Keep-alive для zzap.ru."""
        try:
            logger.debug("[zzap] Keep-alive ping...")

            await self.page.evaluate('''
                fetch("https://www.zzap.ru/", {method: "HEAD", credentials: "include"})
                    .catch(() => {});
            ''')

            logger.debug("[zzap] Keep-alive OK")

        except Exception as e:
            logger.warning(f"[zzap] Keep-alive ошибка: {e}")

    # ========== Методы поиска ==========

    async def search_part(self, partnumber: str, brand_filter: str = None) -> Dict[str, Any]:
        """Выполнить поиск запчасти на zzap.ru.

        Args:
            partnumber: Артикул для поиска
            brand_filter: Фильтр по бренду (необязательно)
        """
        try:
            # Переход на страницу поиска
            url = f"{self.BASE_URL}/public/search.aspx?rawdata={partnumber}"
            logger.info(f"[zzap] Переход: {url}")

            await self.page.goto(url, wait_until='domcontentloaded', timeout=30000)
            await asyncio.sleep(3)

            # Обработка модального окна выбора
            modal_popup = self.page.locator('#ctl00_TopPanel_HeaderPlace_GridLayoutSearchControl_SearchSuggestPopupControl_PWC-1')

            try:
                await modal_popup.wait_for(state='visible', timeout=5000)
                logger.info("[zzap] Модальное окно - выбираем первый вариант")

                first_row = self.page.locator('#ctl00_TopPanel_HeaderPlace_GridLayoutSearchControl_SearchSuggestPopupControl_SearchSuggestGridView_DXDataRow0')

                if await first_row.count() > 0:
                    await first_row.click(timeout=5000)
                    await modal_popup.wait_for(state='hidden', timeout=5000)
                    logger.info("[zzap] Модальное окно закрылось")

            except PlaywrightTimeout:
                logger.info("[zzap] Модальное окно не появилось")

            # Ждём таблицу результатов
            logger.info("[zzap] Ожидание таблицы результатов...")
            try:
                await self.page.wait_for_selector('#ctl00_BodyPlace_SearchGridView_DXMainTable', timeout=15000)
            except PlaywrightTimeout:
                return {
                    'partnumber': partnumber,
                    'status': 'NO_RESULTS',
                    'prices': None,
                    'url': self.page.url
                }

            # Ждём загрузки данных через AJAX
            logger.info("[zzap] Ожидание AJAX данных...")
            for i in range(15):
                page_text = await self.page.inner_text('body')
                if 'Нет никаких данных' not in page_text and 'Одна минута' not in page_text:
                    logger.info(f"[zzap] Данные загрузились за {i+1} сек")
                    break
                await asyncio.sleep(1)

            await asyncio.sleep(2)

            # Парсинг цен и бренда (с фильтрацией если указан brand_filter)
            data = await self._extract_prices_and_brand(brand_filter=brand_filter)
            prices = data['prices']
            brand = data['brand']

            if not prices:
                return {
                    'partnumber': partnumber,
                    'status': 'NO_RESULTS',
                    'prices': None,
                    'brand': brand,
                    'url': self.page.url
                }

            return {
                'partnumber': partnumber,
                'status': 'DONE',
                'prices': {
                    'min': min(prices),
                    'avg': round(sum(prices) / len(prices), 2)
                },
                'brand': brand,
                'url': self.page.url
            }

        except Exception as e:
            logger.error(f"[zzap] Ошибка поиска: {e}")
            raise

    async def search_part_with_retry(self, partnumber: str, brand_filter: str = None, max_retries: int = 3) -> Dict[str, Any]:
        """Поиск с retry."""
        for attempt in range(max_retries):
            try:
                logger.info(f"[zzap] Попытка {attempt + 1}/{max_retries}: {partnumber}" + (f" [бренд: {brand_filter}]" if brand_filter else ""))

                if attempt > 0:
                    import random
                    delay = (2 ** attempt) + random.uniform(0, 1)
                    await asyncio.sleep(delay)

                result = await self.search_part(partnumber, brand_filter=brand_filter)

                if result.get('prices'):
                    logger.info(f"[zzap] Успех! min={result['prices']['min']}, avg={result['prices']['avg']}")
                    return result

            except Exception as e:
                logger.error(f"[zzap] Ошибка попытки {attempt + 1}: {e}")
                if attempt == max_retries - 1:
                    return {
                        'partnumber': partnumber,
                        'status': 'ERROR',
                        'prices': None,
                        'url': None,
                        'error': str(e)
                    }

        return {
            'partnumber': partnumber,
            'status': 'NO_RESULTS',
            'prices': None,
            'url': self.page.url if self.page else None
        }

    async def _extract_prices_and_brand(self, brand_filter: str = None) -> Dict[str, Any]:
        """Извлечь цены и бренд из таблицы результатов zzap.ru.

        Args:
            brand_filter: Если указан, учитывать только строки с этим брендом

        Структура таблицы ZZAP (DevExpress grid):
        - Ячейка [2] содержит БРЕНД (производитель): PEUGEOT CITROEN, Groupe PSA и т.д.
        - Цены в ячейках с классом 'pricewhitecell' в формате "3 083р."
        """
        prices = []
        brand = None
        filtered_count = 0
        total_count = 0

        # Индекс ячейки с брендом в структуре ZZAP
        BRAND_CELL_INDEX = 2

        try:
            table = self.page.locator("table#ctl00_BodyPlace_SearchGridView_DXMainTable")

            if not await table.is_visible(timeout=5000):
                logger.warning("[zzap] Таблица не видна")
                return {'prices': prices, 'brand': brand}

            rows = await table.locator("tr").all()
            logger.info(f"[zzap] Строк в таблице: {len(rows)}")

            if brand_filter:
                logger.info(f"[zzap] Фильтрация по бренду: {brand_filter}")

            for row in rows:
                try:
                    cells = await row.locator("td").all()
                    row_text = await row.inner_text()

                    # Пропускаем служебные строки
                    if "Свернуть" in row_text or "Запрошенный номер" in row_text:
                        continue

                    # Нужно минимум 10 ячеек для строки с данными
                    if len(cells) < 10:
                        continue

                    # Извлекаем бренд из ячейки [2] (PEUGEOT CITROEN)
                    row_brand = None
                    if len(cells) > BRAND_CELL_INDEX:
                        brand_cell = await cells[BRAND_CELL_INDEX].inner_text()
                        brand_cell = brand_cell.strip()
                        # Проверяем что это текст бренда, а не число или служебная информация
                        if brand_cell and len(brand_cell) > 1 and not brand_cell.isdigit():
                            if not any(x in brand_cell.lower() for x in ['свернуть', 'показать', 'р.', '₽']):
                                row_brand = brand_cell.split('\n')[0].strip()
                                if brand is None and row_brand:
                                    brand = row_brand
                                    logger.info(f"[zzap] Найден бренд: {brand}")

                    # Если указан фильтр по бренду - пропускаем строки с другим брендом
                    if brand_filter and row_brand:
                        total_count += 1
                        if brand_filter.lower() not in row_brand.lower():
                            continue
                        filtered_count += 1

                    # Ищем цены в ячейках
                    for cell in cells:
                        cell_text = await cell.inner_text()

                        # Ищем цену: число + "р."
                        if "р." in cell_text and "Заказ от" not in cell_text:
                            match = re.search(r"^(\d[\d\s]*)\s*р\.", cell_text.strip())
                            if match:
                                price_str = match.group(1).replace(" ", "").replace("\xa0", "")
                                try:
                                    price = float(price_str)
                                    if 100 < price < 500000:
                                        prices.append(price)
                                except ValueError:
                                    continue

                except Exception:
                    continue

            prices = list(set(prices))

            if brand_filter and total_count > 0:
                logger.info(f"[zzap] Отфильтровано: {filtered_count}/{total_count} строк по бренду '{brand_filter}'")

            if prices:
                logger.info(f"[zzap] Найдено {len(prices)} цен: {sorted(prices)[:5]}...")

        except Exception as e:
            logger.error(f"[zzap] Ошибка извлечения данных: {e}")

        return {'prices': prices, 'brand': brand}


# ========== Тест ==========

async def test_client():
    """Тест CDP клиента."""
    logging.basicConfig(level=logging.INFO)

    async with ZZapCDPClient() as client:
        print(f"Подключено: {client.is_connected}")
        print(f"URL: {client.url}")

        result = await client.search_part("21126100603082")
        print(f"Результат: {result}")


if __name__ == "__main__":
    asyncio.run(test_client())
