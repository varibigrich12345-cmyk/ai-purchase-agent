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

            # Обработка модального окна выбора бренда
            modal_popup = self.page.locator('#ctl00_TopPanel_HeaderPlace_GridLayoutSearchControl_SearchSuggestPopupControl_PWC-1')

            try:
                await modal_popup.wait_for(state='visible', timeout=5000)

                if brand_filter:
                    # Ищем строку с нужным брендом
                    logger.info(f"[zzap] Модальное окно - ищем бренд '{brand_filter}'")
                    clicked = await self._select_brand_in_modal(modal_popup, brand_filter)
                    if not clicked:
                        logger.warning(f"[zzap] Бренд '{brand_filter}' не найден в модальном окне, выбираем первый")
                        first_row = self.page.locator('#ctl00_TopPanel_HeaderPlace_GridLayoutSearchControl_SearchSuggestPopupControl_SearchSuggestGridView_DXDataRow0')
                        if await first_row.count() > 0:
                            await first_row.click(timeout=5000)
                else:
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

            # Скроллим страницу для подгрузки всех данных
            logger.info("[zzap] Скролл страницы для подгрузки данных...")
            await self.page.evaluate('''
                async () => {
                    const table = document.querySelector('#ctl00_BodyPlace_SearchGridView_DXMainTable');
                    if (table) {
                        // Скроллим к концу таблицы
                        table.scrollIntoView({behavior: 'instant', block: 'end'});
                        await new Promise(r => setTimeout(r, 500));
                        // Скроллим обратно к началу
                        table.scrollIntoView({behavior: 'instant', block: 'start'});
                    }
                }
            ''')
            await asyncio.sleep(1)

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

            # Выбираем минимальную цену среди всех НОВЫХ товаров (исключая б/у)
            min_price = min(prices)
            avg_price = round(sum(prices) / len(prices), 2)
            
            logger.info(f"[zzap] Все найденные цены (новые товары): {sorted(prices)}")
            logger.info(f"[zzap] Минимальная цена: {min_price}₽ (средняя: {avg_price}₽)")

            return {
                'partnumber': partnumber,
                'status': 'DONE',
                'prices': {
                    'min': min_price,
                    'avg': avg_price
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

    async def _select_brand_in_modal(self, modal_popup, brand_filter: str) -> bool:
        """Найти и выбрать нужный бренд в модальном окне ZZAP.

        Args:
            modal_popup: Локатор модального окна
            brand_filter: Название бренда для поиска (case-insensitive)

        Returns:
            True если нашли и кликнули, False иначе
        """
        try:
            # Получаем все строки в модальном окне (DevExpress grid)
            rows = modal_popup.locator("tr[id*='DXDataRow']")
            count = await rows.count()
            logger.info(f"[zzap] В модальном окне {count} вариантов")

            found_brands = []
            brand_filter_lower = brand_filter.lower()

            for i in range(count):
                row = rows.nth(i)
                row_text = await row.inner_text()
                row_text_clean = row_text.strip()

                if row_text_clean:
                    found_brands.append(row_text_clean[:50])  # Для логирования

                # Case-insensitive сравнение
                if brand_filter_lower in row_text.lower():
                    logger.info(f"[zzap] Найден бренд '{brand_filter}' в строке: {row_text_clean[:50]}")
                    await row.click(timeout=5000)
                    return True

            logger.info(f"[zzap] Доступные варианты: {found_brands}")
            return False

        except Exception as e:
            logger.error(f"[zzap] Ошибка выбора бренда в модальном окне: {e}")
            return False

    async def get_brands_for_partnumber(self, partnumber: str) -> List[str]:
        """Получить список брендов для артикула с ZZAP.

        Делает быстрый запрос к ZZAP и извлекает список брендов из модального окна.

        Args:
            partnumber: Артикул для поиска

        Returns:
            Список брендов (например: ['TOYOPOWER', 'TRIALLI', 'GATES'])
        """
        brands = []

        try:
            url = f"{self.BASE_URL}/public/search.aspx?rawdata={partnumber}"
            logger.info(f"[zzap] Получение брендов для: {partnumber}")

            await self.page.goto(url, wait_until='domcontentloaded', timeout=30000)
            await asyncio.sleep(2)

            # Ждём модальное окно с выбором бренда
            modal_popup = self.page.locator('#ctl00_TopPanel_HeaderPlace_GridLayoutSearchControl_SearchSuggestPopupControl_PWC-1')

            try:
                await modal_popup.wait_for(state='visible', timeout=8000)
                logger.info("[zzap] Модальное окно появилось")

                # Извлекаем бренды из строк
                rows = modal_popup.locator("tr[id*='DXDataRow']")
                count = await rows.count()
                logger.info(f"[zzap] Найдено {count} вариантов брендов")

                for i in range(count):
                    row = rows.nth(i)
                    row_text = await row.inner_text()

                    # Формат строки: "BRAND\tPARTNUMBER\tDescription"
                    # Извлекаем первую часть - бренд
                    parts = row_text.strip().split('\t')
                    if parts:
                        brand = parts[0].strip()
                        if brand and brand not in brands:
                            brands.append(brand)

                logger.info(f"[zzap] Найденные бренды: {brands}")

                # Закрываем модальное окно (Escape)
                await self.page.keyboard.press('Escape')
                await asyncio.sleep(0.5)

            except PlaywrightTimeout:
                logger.info("[zzap] Модальное окно не появилось - возможно только один бренд")

                # Пробуем извлечь бренд из таблицы результатов
                try:
                    await self.page.wait_for_selector('#ctl00_BodyPlace_SearchGridView_DXMainTable', timeout=10000)
                    data = await self._extract_prices_and_brand()
                    if data.get('brand'):
                        brands.append(data['brand'])
                except:
                    pass

        except Exception as e:
            logger.error(f"[zzap] Ошибка получения брендов: {e}")

        return brands

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

            for row_idx, row in enumerate(rows, 1):
                try:
                    # Получаем ID строки (DXDataRow<N>)
                    row_id = await row.get_attribute('id') or f"row_{row_idx}"
                    
                    cells = await row.locator("td").all()
                    row_text = await row.inner_text()

                    # ВЫВОДИМ ПОЛНЫЙ ТЕКСТ СТРОКИ для отладки (первые 200 символов)
                    logger.info(f"[zzap] 📋 Строка {row_idx} (ID: {row_id}): {row_text[:200]}")

                    # Пропускаем служебные строки
                    if "Свернуть" in row_text or "Запрошенный номер" in row_text:
                        logger.debug(f"[zzap] Пропуск служебной строки {row_idx}: {row_text[:80]}")
                        continue

                    # ИСКЛЮЧАЕМ б/у товары (строки с "б/у", "б у", "уценка", "бывш")
                    # Берем все НОВЫЕ товары: и "В наличии", и "под заказ"
                    # ВАЖНО: фильтр применяется ДО извлечения цен!
                    row_text_lower = row_text.lower()
                    
                    # Строгая проверка на б/у товары - проверяем различные варианты написания
                    # Проверяем в полном тексте строки (регистронезависимо)
                    has_bu = "б/у" in row_text_lower or "б у" in row_text_lower
                    has_uzenka = "уценка" in row_text_lower
                    has_bu_and_uzenka = "б/у и уценка" in row_text_lower or "б у и уценка" in row_text_lower
                    has_byvsh = "бывш" in row_text_lower or "в употреблении" in row_text_lower
                    
                    is_used = has_bu or has_uzenka or has_bu_and_uzenka or has_byvsh
                    
                    if is_used:
                        # Детальное логирование причины пропуска
                        reasons = []
                        if has_bu:
                            reasons.append("'б/у'")
                        if has_uzenka:
                            reasons.append("'уценка'")
                        if has_bu_and_uzenka:
                            reasons.append("'б/у и уценка'")
                        if has_byvsh:
                            reasons.append("'бывш'")
                        
                        logger.info(f"[zzap] ⛔ ПРОПУСК б/у товара (ID: {row_id}) - найдено: {', '.join(reasons)}")
                        logger.info(f"[zzap] ⛔ Полный текст строки: {row_text[:300]}")
                        continue
                    
                    # Логируем статус товара для отладки
                    if "под заказ" in row_text_lower:
                        logger.debug(f"[zzap] Товар под заказ: {row_text[:80]}")
                    elif "в наличии" in row_text_lower:
                        logger.debug(f"[zzap] Товар в наличии: {row_text[:80]}")

                    # Нужно минимум 10 ячеек для строки с данными
                    if len(cells) < 10:
                        logger.debug(f"[zzap] Пропуск строки: мало ячеек ({len(cells)})")
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
                    if brand_filter:
                        total_count += 1
                        # Если не удалось определить бренд строки - пропускаем
                        if not row_brand:
                            continue
                        
                        # Проверяем: бренд должен начинаться с фильтра ИЛИ содержать его
                        # Примеры: "FORD" → проходит "FORD", "FORD JMC", "FORD USA"
                        brand_filter_lower = brand_filter.lower()
                        row_brand_lower = row_brand.lower()
                        
                        brand_matches = (
                            row_brand_lower.startswith(brand_filter_lower) or
                            brand_filter_lower in row_brand_lower
                        )
                        
                        if not brand_matches:
                            logger.debug(f"[zzap] Пропуск: бренд '{row_brand}' не соответствует фильтру '{brand_filter}'")
                            continue
                        
                        filtered_count += 1
                        logger.debug(f"[zzap] Бренд совпал: '{row_brand}' соответствует фильтру '{brand_filter}'")

                    # Ищем цены в ячейках с ценой (pricewhitecell или другие классы цен)
                    # Расширенный поиск: ищем все ячейки содержащие "р."
                    price_cells = await row.locator("td.pricewhitecell, td.pricecell, td[class*='price']").all()

                    # Если не нашли по классам - ищем во всех ячейках
                    if not price_cells:
                        price_cells = cells

                    # Логируем поставщика для отладки (ячейка с названием магазина)
                    supplier_name = ""
                    try:
                        # Обычно название поставщика в одной из первых ячеек
                        for idx in range(min(5, len(cells))):
                            cell_txt = await cells[idx].inner_text()
                            if cell_txt and len(cell_txt) > 3 and not cell_txt.isdigit():
                                if "р." not in cell_txt and "₽" not in cell_txt:
                                    supplier_name = cell_txt.strip()[:30]
                                    break
                    except:
                        pass

                    for cell in price_cells:
                        cell_text = await cell.inner_text()

                        # Пропускаем ячейки с минимальным заказом, сроком и т.п.
                        if any(x in cell_text.lower() for x in ['заказ от', 'дн.', 'дней', 'шт.']):
                            continue

                        # Ищем цену: число + "р." (не обязательно в начале)
                        if "р." in cell_text:
                            match = re.search(r'(\d[\d\s\xa0]*)\s*р\.', cell_text.strip())
                            if match:
                                price_str = match.group(1).replace(" ", "").replace("\xa0", "")
                                try:
                                    price = float(price_str)
                                    if 50 < price < 500000:
                                        prices.append(price)
                                        # Логируем статус товара для отладки
                                        status_info = ""
                                        if "под заказ" in row_text_lower:
                                            status_info = " [под заказ]"
                                        elif "в наличии" in row_text_lower:
                                            status_info = " [в наличии]"
                                        
                                        # Детальное логирование найденной цены
                                        logger.info(f"[zzap] ✅ НАЙДЕНА ЦЕНА: {price}₽{status_info} | ID: {row_id} | поставщик: {supplier_name} | бренд: {row_brand}")
                                        logger.debug(f"[zzap] Полный текст строки (ID: {row_id}): {row_text[:200]}")
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
