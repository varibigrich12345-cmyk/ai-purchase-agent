"""
CDP клиент для sklad.autotrade.su - подключается к уже запущенному Chrome.

Использование:
1. Запустите start_chrome_debug.bat
2. async with AutoTradeClient() as client:
       result = await client.search_part("ST-FDR8-087-1")
"""

import asyncio
import logging
import re
from typing import Dict, Any, List

from playwright.async_api import TimeoutError as PlaywrightTimeout

from base_browser_client import BaseBrowserClient
from config import AUTOTRADE_EMAIL, AUTOTRADE_PASSWORD

logger = logging.getLogger(__name__)


class AutoTradeClient(BaseBrowserClient):
    """CDP клиент для sklad.autotrade.su с авторизацией и keep-alive."""

    SITE_NAME = "autotrade"
    BASE_URL = "https://sklad.autotrade.su"

    async def check_auth(self) -> bool:
        """Проверить, авторизован ли пользователь на sklad.autotrade.su."""
        try:
            # Переходим на главную для проверки
            if self.BASE_URL not in self.page.url:
                await self.page.goto(self.BASE_URL, wait_until='domcontentloaded', timeout=30000)
                await self.page.wait_for_timeout(2000)

            # Проверяем признаки авторизации
            auth_indicators = [
                'text="Выход"',
                'text="Выйти"',
                'text="выход"',
                '[href*="logout"]',
                'text="Личный кабинет"',
                'text="Корзина"',
                '.user-menu',
                '.logout',
            ]

            for selector in auth_indicators:
                try:
                    if await self.page.locator(selector).count() > 0:
                        logger.info(f"[autotrade] Найден признак авторизации: {selector}")
                        return True
                except:
                    continue

            # Если есть форма логина - не авторизованы
            login_form_indicators = [
                'input[type="email"]',
                'input[name="email"]',
                'input[name="login"]',
                'form[action*="login"]',
            ]

            for selector in login_form_indicators:
                try:
                    if await self.page.locator(selector).is_visible(timeout=2000):
                        logger.info(f"[autotrade] Найдена форма логина: {selector}")
                        return False
                except:
                    continue

            # Проверяем наличие ссылки "Войти"
            try:
                if await self.page.locator('text="Войти"').count() > 0:
                    return False
            except:
                pass

            return False

        except Exception as e:
            logger.error(f"[autotrade] Ошибка проверки авторизации: {e}")
            return False

    async def auto_login(self) -> bool:
        """Выполнить автоматический логин на sklad.autotrade.su."""
        try:
            logger.info("[autotrade] Начинаю автологин...")

            # Переходим на главную страницу
            await self.page.goto(self.BASE_URL, wait_until='networkidle', timeout=60000)
            await self.page.wait_for_timeout(2000)

            # Форма логина на sklad.autotrade.su:
            # - Email: input#log_u (name="log_u")
            # - Пароль: input#log_p (name="log_p")
            # - Кнопка: button#linkLogIn

            # Заполняем email
            email_field = self.page.locator('input#log_u')
            if await email_field.is_visible(timeout=5000):
                await email_field.fill(AUTOTRADE_EMAIL)
                logger.info(f"[autotrade] Email введён: {AUTOTRADE_EMAIL}")
            else:
                logger.error("[autotrade] Поле email (input#log_u) не найдено")
                return False

            # Заполняем пароль
            password_field = self.page.locator('input#log_p')
            if await password_field.is_visible(timeout=3000):
                await password_field.fill(AUTOTRADE_PASSWORD)
                logger.info("[autotrade] Пароль введён")
            else:
                logger.error("[autotrade] Поле пароля (input#log_p) не найдено")
                return False

            # Нажимаем кнопку входа
            login_button = self.page.locator('button#linkLogIn')
            if await login_button.is_visible(timeout=3000):
                await login_button.click()
                logger.info("[autotrade] Нажата кнопка входа")
            else:
                # Fallback: пробуем Enter
                await password_field.press("Enter")
                logger.info("[autotrade] Нажат Enter")

            # Ждём загрузки после логина
            await self.page.wait_for_timeout(5000)

            # Проверяем успешность авторизации
            if await self.check_auth():
                logger.info("[autotrade] Авторизация успешна!")
                return True
            else:
                logger.error("[autotrade] Авторизация не удалась")
                return False

        except Exception as e:
            logger.error(f"[autotrade] Ошибка автологина: {e}")
            return False

    async def keep_alive(self) -> None:
        """Keep-alive для sklad.autotrade.su."""
        try:
            logger.debug("[autotrade] Keep-alive ping...")

            await self.page.evaluate('''
                fetch("https://sklad.autotrade.su/", {method: "HEAD", credentials: "include"})
                    .catch(() => {});
            ''')

            logger.debug("[autotrade] Keep-alive OK")

        except Exception as e:
            logger.warning(f"[autotrade] Keep-alive ошибка: {e}")

    # ========== Методы поиска ==========

    async def search_part(self, partnumber: str, brand_filter: str = None) -> Dict[str, Any]:
        """Выполнить поиск запчасти на sklad.autotrade.su.

        Args:
            partnumber: Артикул для поиска
            brand_filter: Фильтр по бренду (необязательно)
        """
        try:
            # Формируем URL поиска
            search_url = (
                f"{self.BASE_URL}/search/?type=article&q={partnumber}"
                f"&mode=by_full_article&page=1&limit=20&cross=1&replace=1&bycross=0&related=1"
            )
            logger.info(f"[autotrade] Переход: {search_url}")

            await self.page.goto(search_url, wait_until='domcontentloaded', timeout=30000)
            await asyncio.sleep(3)

            # Ждём загрузки результатов
            logger.info("[autotrade] Ожидание результатов поиска...")

            # Ждём появления таблицы или сообщения об отсутствии результатов
            try:
                await self.page.wait_for_selector(
                    'table, .search-results, .no-results, .result-table, [class*="result"]',
                    timeout=15000
                )
            except PlaywrightTimeout:
                logger.info("[autotrade] Таблица результатов не появилась")

            await asyncio.sleep(2)

            # Проверяем наличие результатов
            page_text = await self.page.inner_text('body')
            no_results_indicators = [
                'ничего не найдено',
                'нет результатов',
                'не найдено',
                'no results',
            ]

            for indicator in no_results_indicators:
                if indicator.lower() in page_text.lower():
                    return {
                        'partnumber': partnumber,
                        'status': 'NO_RESULTS',
                        'prices': None,
                        'brand': None,
                        'url': self.page.url
                    }

            # Парсинг результатов
            data = await self._extract_prices_and_brand(brand_filter=brand_filter)
            prices = data['prices']
            brand = data['brand']
            items = data.get('items', [])

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
                'items': items,
                'url': self.page.url
            }

        except Exception as e:
            logger.error(f"[autotrade] Ошибка поиска: {e}")
            raise

    async def search_part_with_retry(self, partnumber: str, brand_filter: str = None, max_retries: int = 3) -> Dict[str, Any]:
        """Поиск с retry."""
        for attempt in range(max_retries):
            try:
                logger.info(f"[autotrade] Попытка {attempt + 1}/{max_retries}: {partnumber}" + (f" [бренд: {brand_filter}]" if brand_filter else ""))

                if attempt > 0:
                    import random
                    delay = (2 ** attempt) + random.uniform(0, 1)
                    await asyncio.sleep(delay)

                result = await self.search_part(partnumber, brand_filter=brand_filter)

                if result.get('prices'):
                    logger.info(f"[autotrade] Успех! min={result['prices']['min']}, avg={result['prices']['avg']}")
                    return result

            except Exception as e:
                logger.error(f"[autotrade] Ошибка попытки {attempt + 1}: {e}")
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
        """Извлечь цены, бренд и наличие из результатов sklad.autotrade.su.

        Формат строки результата:
        "Артикул: ST-FDR8-087-1, Бренд: SAT, Страна: КИТАЙ, ... | Цена ... | 935 RUB | наличие: 11, 22..."

        Args:
            brand_filter: Если указан, учитывать только строки с этим брендом
        """
        prices = []
        brand = None
        items = []
        filtered_count = 0
        total_count = 0

        try:
            # Получаем весь текст страницы для парсинга
            body_text = await self.page.inner_text('body')

            # Ищем строки с данными о товарах
            # Формат: "Артикул: XXX, Бренд: YYY, Страна: ZZZ"
            article_pattern = r'Артикул:\s*([A-Za-z0-9\-\.]+)'
            brand_pattern = r'Бренд:\s*([A-Za-zА-Яа-я0-9\-\s]+?)(?:,|$|\|)'
            country_pattern = r'Страна:\s*([А-Яа-я]+)'
            price_pattern = r'(\d[\d\s,\.]*)\s*RUB'

            # Извлекаем артикул
            article_match = re.search(article_pattern, body_text)
            if article_match:
                article = article_match.group(1).strip()
                logger.info(f"[autotrade] Найден артикул: {article}")

            # Извлекаем бренд
            brand_match = re.search(brand_pattern, body_text)
            if brand_match:
                brand = brand_match.group(1).strip()
                logger.info(f"[autotrade] Найден бренд: {brand}")

            # Извлекаем все цены
            price_matches = re.findall(price_pattern, body_text)
            for pm in price_matches:
                try:
                    price_str = pm.replace(" ", "").replace("\xa0", "").replace(",", ".")
                    price_val = float(price_str)
                    # Фильтруем разумные цены (исключаем 0.00 и слишком большие)
                    if 10 < price_val < 500000:
                        prices.append(price_val)
                except ValueError:
                    pass

            # Ищем наличие (числа в ячейках таблицы)
            stock_values = []
            tables = self.page.locator('table')
            tables_count = await tables.count()

            for t_idx in range(tables_count):
                table = tables.nth(t_idx)
                rows = table.locator('tr')
                rows_count = await rows.count()

                for r_idx in range(rows_count):
                    row = rows.nth(r_idx)
                    row_text = await row.inner_text()

                    # Ищем строки с данными о товаре (содержат "Артикул:" или цену RUB)
                    if 'Артикул:' in row_text or 'RUB' in row_text:
                        # Извлекаем цену из этой строки
                        row_price_match = re.search(r'(\d[\d\s,\.]*)\s*RUB', row_text)
                        if row_price_match:
                            try:
                                price_str = row_price_match.group(1).replace(" ", "").replace("\xa0", "").replace(",", ".")
                                price_val = float(price_str)
                                if 10 < price_val < 500000 and price_val not in prices:
                                    prices.append(price_val)
                            except ValueError:
                                pass

                        # Извлекаем наличие (числа после описания товара)
                        # Формат: "... | 11 | 22 | - | - |..."
                        stock_matches = re.findall(r'\|\s*(\d+)\s*\|', row_text)
                        for sm in stock_matches:
                            try:
                                stock = int(sm)
                                if 0 < stock < 10000:
                                    stock_values.append(stock)
                            except ValueError:
                                pass

                        # Также ищем наличие в формате табуляции
                        parts = row_text.split('\t')
                        for part in parts:
                            part = part.strip()
                            if re.match(r'^\d+$', part):
                                try:
                                    stock = int(part)
                                    if 0 < stock < 10000:
                                        stock_values.append(stock)
                                except ValueError:
                                    pass

            # Убираем дубликаты
            prices = list(set(prices))
            stock_values = list(set(stock_values))

            if prices:
                logger.info(f"[autotrade] Найдено {len(prices)} цен: {sorted(prices)[:5]}...")

            if stock_values:
                logger.info(f"[autotrade] Наличие: {stock_values[:10]}")

            # Формируем items
            if prices:
                items.append({
                    'article': article_match.group(1).strip() if article_match else None,
                    'brand': brand,
                    'price': min(prices) if prices else None,
                    'stock': sum(stock_values) if stock_values else None,
                })

        except Exception as e:
            logger.error(f"[autotrade] Ошибка извлечения данных: {e}")

        return {'prices': prices, 'brand': brand, 'items': items}

    async def _extract_from_cards(self, brand_filter: str = None) -> Dict[str, Any]:
        """Извлечь данные из карточного формата (если не таблица)."""
        prices = []
        brand = None
        items = []

        try:
            # Ищем карточки товаров
            card_selectors = [
                '.product-card',
                '.item-card',
                '.search-item',
                '[class*="product"]',
                '[class*="item"]',
            ]

            cards = None
            for selector in card_selectors:
                try:
                    c = self.page.locator(selector)
                    if await c.count() > 0:
                        cards = c
                        logger.info(f"[autotrade] Найдены карточки: {selector}")
                        break
                except:
                    continue

            if not cards:
                # Пробуем извлечь из всей страницы
                page_text = await self.page.inner_text('body')

                # Ищем цены на странице
                price_matches = re.findall(r'([\d\s\.,]+)\s*(RUB|руб|₽)', page_text, re.IGNORECASE)
                for match in price_matches:
                    try:
                        price_str = match[0].replace(" ", "").replace("\xa0", "").replace(",", ".")
                        price_val = float(price_str)
                        if 10 < price_val < 500000:
                            prices.append(price_val)
                    except ValueError:
                        pass

                # Ищем бренды
                brand_patterns = [
                    r'\b(SAT|FEBI|GATES|TRW|BOSCH|DENSO|NGK|SACHS|LUK|INA|FAG|SKF|NTN|KOYO|NSK)\b',
                ]
                for pattern in brand_patterns:
                    match = re.search(pattern, page_text, re.IGNORECASE)
                    if match:
                        brand = match.group(1).upper()
                        break

                prices = list(set(prices))
                return {'prices': prices, 'brand': brand, 'items': items}

            # Парсим карточки
            count = await cards.count()
            logger.info(f"[autotrade] Карточек найдено: {count}")

            for i in range(min(count, 50)):  # Ограничиваем до 50
                card = cards.nth(i)
                card_text = await card.inner_text()

                # Извлекаем цену
                price_match = re.search(r'([\d\s\.,]+)\s*(RUB|руб|₽|р\.?)', card_text, re.IGNORECASE)
                if price_match:
                    try:
                        price_str = price_match.group(1).replace(" ", "").replace("\xa0", "").replace(",", ".")
                        price_val = float(price_str)
                        if 10 < price_val < 500000:
                            prices.append(price_val)
                    except ValueError:
                        pass

                # Извлекаем бренд
                if not brand:
                    brand_patterns = [
                        r'\b(SAT|FEBI|GATES|TRW|BOSCH|DENSO|NGK|SACHS|LUK|INA|FAG|SKF|NTN|KOYO|NSK)\b',
                    ]
                    for pattern in brand_patterns:
                        match = re.search(pattern, card_text, re.IGNORECASE)
                        if match:
                            brand = match.group(1).upper()
                            break

            prices = list(set(prices))

        except Exception as e:
            logger.error(f"[autotrade] Ошибка извлечения из карточек: {e}")

        return {'prices': prices, 'brand': brand, 'items': items}

    async def get_brands_for_partnumber(self, partnumber: str) -> List[str]:
        """Получить список брендов для артикула с AutoTrade.

        Args:
            partnumber: Артикул для поиска

        Returns:
            Список брендов (например: ['SAT', 'FEBI', 'GATES'])
        """
        brands = []

        try:
            search_url = (
                f"{self.BASE_URL}/search/?type=article&q={partnumber}"
                f"&mode=by_full_article&page=1&limit=20&cross=1&replace=1&bycross=0&related=1"
            )
            logger.info(f"[autotrade] Получение брендов для: {partnumber}")

            await self.page.goto(search_url, wait_until='domcontentloaded', timeout=30000)
            await asyncio.sleep(3)

            # Извлекаем бренды из результатов
            data = await self._extract_prices_and_brand()
            items = data.get('items', [])

            for item in items:
                if item.get('brand') and item['brand'] not in brands:
                    brands.append(item['brand'])

            if data.get('brand') and data['brand'] not in brands:
                brands.append(data['brand'])

            logger.info(f"[autotrade] Найденные бренды: {brands}")

        except Exception as e:
            logger.error(f"[autotrade] Ошибка получения брендов: {e}")

        return brands


# ========== Тест ==========

async def test_client():
    """Тест CDP клиента."""
    logging.basicConfig(level=logging.INFO)

    async with AutoTradeClient() as client:
        print(f"Подключено: {client.is_connected}")
        print(f"Авторизован: {client.is_logged_in}")
        print(f"URL: {client.url}")

        # Тестовый поиск
        result = await client.search_part("ST-FDR8-087-1")
        print(f"Результат: {result}")


if __name__ == "__main__":
    asyncio.run(test_client())
