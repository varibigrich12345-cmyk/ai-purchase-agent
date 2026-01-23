"""
CDP клиент для stparts.ru - подключается к уже запущенному Chrome.

Использование:
1. Запустите start_chrome_debug.bat
2. async with STPartsCDPClient() as client:
       result = await client.search_part("12345")
"""

import asyncio
import logging
import re
from typing import Dict, Any, List

from base_browser_client import BaseBrowserClient
from config import STPARTS_LOGIN, STPARTS_PASSWORD

logger = logging.getLogger(__name__)


class STPartsCDPClient(BaseBrowserClient):
    """CDP клиент для stparts.ru с авторизацией и keep-alive."""

    SITE_NAME = "stparts"
    BASE_URL = "https://stparts.ru"

    async def check_auth(self) -> bool:
        """Проверить, авторизован ли пользователь на stparts.ru."""
        try:
            # Переходим на страницу клиентов для проверки
            clients_url = f"{self.BASE_URL}/clients"
            if clients_url not in self.page.url:
                await self.page.goto(clients_url, wait_until='domcontentloaded', timeout=30000)
                await self.page.wait_for_timeout(2000)

            # Проверяем признаки авторизации
            auth_indicators = [
                'text="Выход"',
                'text="Выйти"',
                'text="выход"',
                '[href*="logout"]',
                'text="Личный кабинет"',
            ]

            for selector in auth_indicators:
                try:
                    if await self.page.locator(selector).count() > 0:
                        logger.info(f"[stparts] Найден признак авторизации: {selector}")
                        return True
                except:
                    continue

            # Если есть форма логина (поле пароля видно) - не авторизованы
            if await self.page.locator('input[name="pass"]').count() > 0:
                return False

            return False

        except Exception as e:
            logger.error(f"[stparts] Ошибка проверки авторизации: {e}")
            return False

    async def auto_login(self) -> bool:
        """Выполнить автоматический логин на stparts.ru."""
        try:
            logger.info("[stparts] Начинаю автологин...")

            # Переходим на страницу клиентов (там форма входа)
            login_url = f"{self.BASE_URL}/clients"
            await self.page.goto(login_url, wait_until='networkidle', timeout=60000)
            await self.page.wait_for_timeout(2000)

            # Отладка - сохраняем скриншот и HTML
            await self.page.screenshot(path='/tmp/stparts_login.png')
            html_content = await self.page.content()
            logger.info(f"[stparts] HTML страницы (первые 2000 символов): {html_content[:2000]}")
            logger.info(f"[stparts] URL страницы: {self.page.url}")

            # Заполняем логин (input[name="login"])
            login_field = 'input[name="login"]'
            if await self.page.locator(login_field).count() > 0:
                await self.page.fill(login_field, STPARTS_LOGIN)
                logger.info(f"[stparts] Логин введён: {STPARTS_LOGIN}")
            else:
                logger.error("[stparts] Поле логина не найдено")
                return False

            # Заполняем пароль (input[name="pass"])
            password_field = 'input[name="pass"]'
            if await self.page.locator(password_field).count() > 0:
                await self.page.fill(password_field, STPARTS_PASSWORD)
            else:
                logger.error("[stparts] Поле пароля не найдено")
                return False

            # Нажимаем кнопку входа (submit рядом с формой)
            try:
                # Ищем submit кнопку в форме авторизации
                await self.page.locator('input[name="pass"]').press("Enter")
            except:
                try:
                    await self.page.click('input[type="submit"][name="go"]')
                except:
                    logger.error("[stparts] Кнопка входа не найдена")
                    return False

            # Ждём загрузки
            await self.page.wait_for_timeout(5000)

            # Проверяем успешность - должны увидеть признаки авторизации
            if await self.check_auth():
                logger.info("[stparts] Авторизация успешна!")
                return True
            else:
                logger.error("[stparts] Авторизация не удалась")
                return False

        except Exception as e:
            logger.error(f"[stparts] Ошибка автологина: {e}")
            return False

    async def keep_alive(self) -> None:
        """Специфичный keep-alive для stparts.ru."""
        try:
            logger.debug("[stparts] Keep-alive: проверка сессии...")

            # Делаем лёгкий запрос к API или главной
            await self.page.evaluate('''
                fetch("/api/user/current", {method: "GET", credentials: "include"})
                    .catch(() => fetch("/", {method: "HEAD", credentials: "include"}))
                    .catch(() => {});
            ''')

            logger.debug("[stparts] Keep-alive OK")

        except Exception as e:
            logger.warning(f"[stparts] Keep-alive ошибка: {e}")

    # ========== Методы поиска ==========

    async def search_part(self, partnumber: str, brand_filter: str = None) -> Dict[str, Any]:
        """Поиск запчасти по артикулу.

        Args:
            partnumber: Артикул для поиска
            brand_filter: Фильтр по бренду (необязательно)
        """
        try:
            # Если указан brand_filter - сразу переходим на URL результатов
            if brand_filter:
                # Бренд в URL может содержать дефис вместо пробелов (Peugeot-Citroen)
                brand_url = brand_filter.replace(' ', '-')
                search_url = f"{self.BASE_URL}/search/{brand_url}/{partnumber}"
                logger.info(f"[stparts] Переход на URL результатов: {search_url}")
                await self.page.goto(search_url, wait_until='networkidle', timeout=60000)
                await self.page.wait_for_timeout(3000)
            else:
                # Если brand_filter не указан - используем старый метод через /clients
                await self.page.goto(f"{self.BASE_URL}/clients", wait_until='networkidle', timeout=60000)
                await self.page.wait_for_timeout(2000)

                # Ищем поле поиска по артикулу (input[name="pcode"])
                search_field = 'input[name="pcode"]'
                if await self.page.locator(search_field).count() > 0:
                    await self.page.fill(search_field, partnumber)
                    await self.page.press(search_field, "Enter")
                else:
                    return {
                        'partnumber': partnumber,
                        'status': 'error',
                        'prices': {'min': None, 'avg': None},
                        'error': 'Поле поиска не найдено'
                    }

                logger.info(f"[stparts] Поиск: {partnumber}")
                await self.page.wait_for_timeout(5000)

                # Пробуем нажать "Цены и аналоги"
                try:
                    link = self.page.get_by_role("link", name="Цены и аналоги").first
                    if await link.is_visible(timeout=5000):
                        await link.click()
                        await self.page.wait_for_timeout(3000)
                        logger.info("[stparts] Перешли на страницу цен")
                except:
                    logger.debug("[stparts] Ссылка 'Цены и аналоги' не найдена")

            # Извлекаем цены и бренд (с фильтрацией если указан brand_filter)
            data = await self._extract_prices_and_brand(brand_filter=brand_filter)
            prices = data['prices']
            brand = data['brand']

            if not prices:
                return {
                    'partnumber': partnumber,
                    'status': 'not_found',
                    'prices': {'min': None, 'avg': None},
                    'brand': brand,
                    'url': self.page.url
                }

            return {
                'partnumber': partnumber,
                'status': 'success',
                'prices': {
                    'min': min(prices),
                    'avg': round(sum(prices) / len(prices), 2)
                },
                'brand': brand,
                'url': self.page.url
            }

        except Exception as e:
            logger.error(f"[stparts] Ошибка поиска: {e}")
            return {
                'partnumber': partnumber,
                'status': 'error',
                'prices': {'min': None, 'avg': None},
                'error': str(e)
            }

    async def search_part_with_retry(self, partnumber: str, brand_filter: str = None, max_retries: int = 3) -> Dict[str, Any]:
        """Поиск с повторными попытками."""
        for attempt in range(1, max_retries + 1):
            logger.info(f"[stparts] Попытка {attempt}/{max_retries}: {partnumber}" + (f" [бренд: {brand_filter}]" if brand_filter else ""))

            result = await self.search_part(partnumber, brand_filter=brand_filter)

            if result.get('status') == 'success' and result.get('prices', {}).get('min'):
                return result

            if attempt < max_retries:
                await asyncio.sleep(2 * attempt)

        return result

    async def _click_brand_row(self, brand_filter: str) -> bool:
        """Найти и кликнуть на строку с нужным брендом в результатах поиска.

        На странице /search?pcode=XXX показывается список брендов с ссылками
        "Цены и аналоги" -> /search/{brand}/{partnumber}

        Args:
            brand_filter: Название бренда для поиска (например, "Peugeot")

        Returns:
            True если нашли и кликнули, False иначе
        """
        logger.info(f"[stparts] Поиск бренда '{brand_filter}' на странице {self.page.url}")

        try:
            # Ищем ссылки "Цены и аналоги" которые ведут на страницу нужного бренда
            # Формат ссылки: /search/{brand}/{partnumber}
            all_links = await self.page.locator("a").all()
            found_brands = []

            for link in all_links:
                href = await link.get_attribute("href") or ""
                text = (await link.inner_text()).strip()

                # Ищем ссылки формата /search/Brand/PartNumber
                if "/search/" in href and text == "Цены и аналоги":
                    # Извлекаем бренд из URL: /search/Peugeot-Citroen/1920QK -> Peugeot-Citroen
                    parts = href.split("/")
                    if len(parts) >= 3:
                        url_brand = parts[2]  # Бренд в URL
                        if url_brand not in found_brands:
                            found_brands.append(url_brand)

                        # Проверяем совпадение бренда (без учёта регистра, частичное)
                        if brand_filter.lower() in url_brand.lower() or url_brand.lower() in brand_filter.lower():
                            logger.info(f"[stparts] Найден бренд '{url_brand}', кликаем на '{href}'")
                            await link.click()
                            await self.page.wait_for_timeout(3000)
                            logger.info(f"[stparts] Перешли на страницу бренда: {self.page.url}")
                            return True

            logger.warning(f"[stparts] Бренд '{brand_filter}' не найден. Доступные: {found_brands}")
            return False

        except Exception as e:
            logger.error(f"[stparts] Ошибка при клике на бренд: {e}")
            return False

    async def _extract_prices_and_brand(self, brand_filter: str = None) -> Dict[str, Any]:
        """Извлечь цены и бренд из таблицы результатов.

        Args:
            brand_filter: Если указан, учитывать только строки с этим брендом

        Структура таблицы STparts:
        - Ячейка [2] с классом 'resultBrand' содержит БРЕНД (CGA, Peugeot и т.д.)
        - Цены в формате "1 234,56 ₽"
        """
        prices = []
        brand = None
        filtered_count = 0
        total_count = 0

        # Индекс ячейки с брендом в структуре STparts
        BRAND_CELL_INDEX = 2

        try:
            table = self.page.locator("#searchResultsTable")
            await table.wait_for(state="visible", timeout=10000)

            rows = table.locator("tbody tr")
            count = await rows.count()
            logger.info(f"[stparts] Найдено {count} строк в таблице")

            if brand_filter:
                logger.info(f"[stparts] Фильтрация по бренду: {brand_filter}")

            for i in range(count):
                row = rows.nth(i)
                row_text = await row.inner_text()

                # Пропускаем строки-заголовки групп
                if 'resultTitleMain' in (await row.get_attribute("class") or ""):
                    continue

                # Извлекаем бренд из ячейки [2] (класс resultBrand)
                row_brand = None
                cells = row.locator("td")
                cells_count = await cells.count()

                # Пробуем найти ячейку с классом resultBrand
                brand_cell = row.locator("td.resultBrand")
                if await brand_cell.count() > 0:
                    brand_text = await brand_cell.first.inner_text()
                    brand_text = brand_text.strip()
                    if brand_text and len(brand_text) > 0:
                        row_brand = brand_text.split('\n')[0].strip()
                        if brand is None and row_brand:
                            brand = row_brand
                            logger.info(f"[stparts] Найден бренд: {brand}")
                elif cells_count > BRAND_CELL_INDEX:
                    # Fallback: берём из ячейки [2]
                    brand_text = await cells.nth(BRAND_CELL_INDEX).inner_text()
                    brand_text = brand_text.strip()
                    if brand_text and len(brand_text) > 0 and not re.search(r'[\d₽]', brand_text):
                        row_brand = brand_text.split('\n')[0].strip()
                        if brand is None and row_brand:
                            brand = row_brand
                            logger.info(f"[stparts] Найден бренд (fallback): {brand}")

                # Если указан фильтр по бренду - пропускаем строки с другим брендом
                if brand_filter and row_brand:
                    total_count += 1
                    if brand_filter.lower() not in row_brand.lower():
                        continue
                    filtered_count += 1

                # Ищем цену в формате "141,40 ₽" или "1 234,56 ₽"
                match = re.search(r"([\d\s]+[,.]?\d*)\s*₽", row_text)
                if match:
                    try:
                        price_str = match.group(1).replace(" ", "").replace("\xa0", "").replace(",", ".")
                        val = float(price_str)
                        if 10 < val < 500000:
                            prices.append(val)
                    except ValueError:
                        pass

        except Exception as e:
            logger.debug(f"[stparts] Ошибка извлечения данных: {e}")

        if brand_filter and total_count > 0:
            logger.info(f"[stparts] Отфильтровано: {filtered_count}/{total_count} строк по бренду '{brand_filter}'")

        unique_prices = list(set(prices))
        if unique_prices:
            logger.info(f"[stparts] Найдено {len(unique_prices)} уникальных цен: {sorted(unique_prices)[:5]}...")
        return {'prices': unique_prices, 'brand': brand}


# ========== Тест ==========

async def test_client():
    """Тест CDP клиента."""
    logging.basicConfig(level=logging.INFO)

    async with STPartsCDPClient() as client:
        print(f"Подключено: {client.is_connected}")
        print(f"Авторизован: {client.is_logged_in}")
        print(f"URL: {client.url}")

        # Тестовый поиск
        result = await client.search_part("21126100603082")
        print(f"Результат: {result}")


if __name__ == "__main__":
    asyncio.run(test_client())
