"""
CDP клиент для trast.ru - подключается к уже запущенному Chrome.

Использование:
1. Запустите start_chrome_debug.bat
2. async with TrastCDPClient() as client:
       result = await client.search_part("12345")
"""

import asyncio
import logging
import re
from typing import Dict, Any, List

from base_browser_client import BaseBrowserClient
from config import TRAST_LOGIN, TRAST_PASSWORD

logger = logging.getLogger(__name__)


class TrastCDPClient(BaseBrowserClient):
    """CDP клиент для trast-zapchast.ru с авторизацией и keep-alive."""

    SITE_NAME = "trast"
    BASE_URL = "https://trast-zapchast.ru"

    async def check_auth(self) -> bool:
        """Проверить, авторизован ли пользователь на trast.ru."""
        try:
            # Переходим на главную страницу для проверки
            if self.BASE_URL not in self.page.url:
                await self.page.goto(self.BASE_URL, wait_until='domcontentloaded', timeout=30000)
                await self.page.wait_for_timeout(2000)

            # Проверяем признаки авторизации
            auth_indicators = [
                'text="Выход"',
                'text="Выйти"',
                'text="Личный кабинет"',
                '[href*="logout"]',
                '[href*="exit"]',
                '.user-menu',
                '.account-menu',
            ]

            for selector in auth_indicators:
                try:
                    if await self.page.locator(selector).count() > 0:
                        logger.info(f"[trast] Найден признак авторизации: {selector}")
                        return True
                except:
                    continue

            # Если есть форма логина - не авторизованы
            if await self.page.locator('input[type="password"]').count() > 0:
                return False

            return False

        except Exception as e:
            logger.error(f"[trast] Ошибка проверки авторизации: {e}")
            return False

    async def auto_login(self) -> bool:
        """Выполнить автоматический логин на trast.ru."""
        try:
            logger.info("[trast] Начинаю автологин...")

            # Переходим на страницу входа
            login_url = f"{self.BASE_URL}/login/"
            await self.page.goto(login_url, wait_until='networkidle', timeout=60000)
            await self.page.wait_for_timeout(2000)

            # Ищем поле логина (разные варианты)
            login_selectors = [
                'input[name="login"]',
                'input[name="email"]',
                'input[name="username"]',
                'input[name="USER_LOGIN"]',  # Bitrix
                'input[name="AUTH_LOGIN"]',  # Bitrix
                'input[name="AUTH[LOGIN]"]',  # Bitrix array
                'input[name="user_login"]',
                'input[name="user"]',
                'input[name="phone"]',
                'input[type="email"]',
                'input[type="tel"]',  # Phone login
                'input[id="login"]',
                'input[id="email"]',
                'input[placeholder*="логин" i]',
                'input[placeholder*="email" i]',
                'input[placeholder*="почт" i]',
                'input[placeholder*="телефон" i]',
                '#USER_LOGIN',  # Bitrix ID
                '#AUTH_LOGIN',
            ]

            login_field = None
            for selector in login_selectors:
                if await self.page.locator(selector).count() > 0:
                    login_field = selector
                    break

            if login_field:
                await self.page.fill(login_field, TRAST_LOGIN)
                logger.info(f"[trast] Логин введён в поле: {login_field}")
            else:
                # Debug: выводим все input на странице
                try:
                    inputs = await self.page.locator('input').all()
                    logger.error(f"[trast] Поле логина не найдено. Найдено {len(inputs)} input элементов:")
                    for inp in inputs[:10]:  # Первые 10
                        attrs = await inp.evaluate('el => ({name: el.name, type: el.type, id: el.id, placeholder: el.placeholder})')
                        logger.error(f"  input: {attrs}")
                except Exception as e:
                    logger.error(f"[trast] Поле логина не найдено, debug ошибка: {e}")
                return False

            # Ищем поле пароля
            password_selectors = [
                'input[name="password"]',
                'input[name="pass"]',
                'input[type="password"]',
            ]

            password_field = None
            for selector in password_selectors:
                if await self.page.locator(selector).count() > 0:
                    password_field = selector
                    break

            if password_field:
                await self.page.fill(password_field, TRAST_PASSWORD)
            else:
                logger.error("[trast] Поле пароля не найдено")
                return False

            # Нажимаем кнопку входа
            submit_selectors = [
                'button[type="submit"]',
                'input[type="submit"]',
                'button:has-text("Войти")',
                'button:has-text("Вход")',
            ]

            for selector in submit_selectors:
                try:
                    if await self.page.locator(selector).count() > 0:
                        await self.page.click(selector)
                        break
                except:
                    continue

            # Ждём загрузки
            await self.page.wait_for_timeout(5000)

            # Проверяем успешность
            if await self.check_auth():
                logger.info("[trast] Авторизация успешна!")
                return True
            else:
                logger.error("[trast] Авторизация не удалась")
                return False

        except Exception as e:
            logger.error(f"[trast] Ошибка автологина: {e}")
            return False

    async def keep_alive(self) -> None:
        """Keep-alive для trast.ru."""
        try:
            logger.debug("[trast] Keep-alive: проверка сессии...")

            await self.page.evaluate('''
                fetch("/", {method: "HEAD", credentials: "include"})
                    .catch(() => {});
            ''')

            logger.debug("[trast] Keep-alive OK")

        except Exception as e:
            logger.warning(f"[trast] Keep-alive ошибка: {e}")

    # ========== Методы поиска ==========

    async def search_part(self, partnumber: str, brand_filter: str = None) -> Dict[str, Any]:
        """Поиск запчасти по артикулу.

        Args:
            partnumber: Артикул для поиска
            brand_filter: Фильтр по бренду (необязательно)
        """
        try:
            # Формируем URL поиска
            search_url = f"{self.BASE_URL}/search/?query={partnumber}"
            await self.page.goto(search_url, wait_until='networkidle', timeout=60000)
            await self.page.wait_for_timeout(3000)

            logger.info(f"[trast] Поиск: {partnumber}")

            # Если указан brand_filter, пробуем найти и кликнуть на бренд
            if brand_filter:
                logger.info(f"[trast] Фильтр по бренду: {brand_filter}")
                await self._click_brand_if_found(brand_filter)
                await self.page.wait_for_timeout(2000)

            # Извлекаем цены и бренд
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
            logger.error(f"[trast] Ошибка поиска: {e}")
            return {
                'partnumber': partnumber,
                'status': 'error',
                'prices': {'min': None, 'avg': None},
                'error': str(e)
            }

    async def search_part_with_retry(self, partnumber: str, brand_filter: str = None, max_retries: int = 3) -> Dict[str, Any]:
        """Поиск с повторными попытками."""
        for attempt in range(1, max_retries + 1):
            logger.info(f"[trast] Попытка {attempt}/{max_retries}: {partnumber}" + (f" [бренд: {brand_filter}]" if brand_filter else ""))

            result = await self.search_part(partnumber, brand_filter=brand_filter)

            if result.get('status') == 'success' and result.get('prices', {}).get('min'):
                return result

            if attempt < max_retries:
                await asyncio.sleep(2 * attempt)

        return result

    async def _click_brand_if_found(self, brand_filter: str) -> bool:
        """Найти и кликнуть на бренд если есть выбор."""
        try:
            # Ищем ссылки/кнопки с названием бренда
            brand_lower = brand_filter.lower()

            # Пробуем разные селекторы для бренда
            selectors = [
                f'a:has-text("{brand_filter}")',
                f'button:has-text("{brand_filter}")',
                f'.brand-item:has-text("{brand_filter}")',
                f'[data-brand*="{brand_lower}" i]',
            ]

            for selector in selectors:
                try:
                    locator = self.page.locator(selector).first
                    if await locator.is_visible(timeout=2000):
                        await locator.click()
                        logger.info(f"[trast] Кликнули на бренд: {brand_filter}")
                        return True
                except:
                    continue

            return False

        except Exception as e:
            logger.debug(f"[trast] Бренд не найден для клика: {e}")
            return False

    async def _extract_prices_and_brand(self, brand_filter: str = None) -> Dict[str, Any]:
        """Извлечь цены и бренд из результатов поиска."""
        prices = []
        brand = None
        filtered_count = 0
        total_count = 0

        try:
            # Ждём появления результатов
            await self.page.wait_for_timeout(2000)

            # Получаем весь текст страницы для анализа
            page_text = await self.page.content()

            # Ищем бренд на странице
            brand_patterns = [
                r'data-brand="([^"]+)"',
                r'class="brand[^"]*"[^>]*>([^<]+)<',
                r'Производитель:\s*([^<\n]+)',
                r'Бренд:\s*([^<\n]+)',
            ]

            for pattern in brand_patterns:
                match = re.search(pattern, page_text, re.IGNORECASE)
                if match:
                    brand = match.group(1).strip()
                    if brand and len(brand) > 1 and len(brand) < 50:
                        logger.info(f"[trast] Найден бренд: {brand}")
                        break

            # Ищем таблицу результатов (разные варианты)
            table_selectors = [
                'table.results',
                'table.search-results',
                '.results-table',
                '#searchResults',
                'table tbody tr',
            ]

            rows = None
            for selector in table_selectors:
                try:
                    locator = self.page.locator(selector)
                    if await locator.count() > 0:
                        if 'tr' in selector:
                            rows = locator
                        else:
                            rows = locator.locator('tr')
                        break
                except:
                    continue

            if rows:
                count = await rows.count()
                logger.info(f"[trast] Найдено {count} строк")

                for i in range(min(count, 100)):  # Ограничиваем 100 строками
                    row = rows.nth(i)
                    row_text = await row.inner_text()

                    # Если есть фильтр по бренду - проверяем
                    if brand_filter:
                        total_count += 1
                        if brand_filter.lower() not in row_text.lower():
                            continue
                        filtered_count += 1

                    # Ищем цену в разных форматах
                    price_patterns = [
                        r"([\d\s]+[,.]?\d*)\s*₽",
                        r"([\d\s]+[,.]?\d*)\s*руб",
                        r"([\d\s]+[,.]?\d*)\s*RUB",
                        r"цена[:\s]*([\d\s]+[,.]?\d*)",
                    ]

                    for pattern in price_patterns:
                        match = re.search(pattern, row_text, re.IGNORECASE)
                        if match:
                            try:
                                price_str = match.group(1).replace(" ", "").replace("\xa0", "").replace(",", ".")
                                val = float(price_str)
                                if 10 < val < 500000:
                                    prices.append(val)
                                    break
                            except ValueError:
                                pass

            # Если не нашли в таблице, ищем цены в тексте страницы
            if not prices:
                # Ищем все цены на странице
                all_prices = re.findall(r"([\d\s]{1,10}[,.]?\d{0,2})\s*₽", page_text)
                for price_str in all_prices:
                    try:
                        price_str = price_str.replace(" ", "").replace("\xa0", "").replace(",", ".")
                        val = float(price_str)
                        if 100 < val < 500000:  # Разумный диапазон цен
                            prices.append(val)
                    except ValueError:
                        pass

        except Exception as e:
            logger.debug(f"[trast] Ошибка извлечения данных: {e}")

        if brand_filter and total_count > 0:
            logger.info(f"[trast] Отфильтровано: {filtered_count}/{total_count} строк по бренду '{brand_filter}'")

        unique_prices = list(set(prices))
        if unique_prices:
            logger.info(f"[trast] Найдено {len(unique_prices)} уникальных цен: {sorted(unique_prices)[:5]}...")

        return {'prices': unique_prices, 'brand': brand}


# ========== Тест ==========

async def test_client():
    """Тест CDP клиента."""
    logging.basicConfig(level=logging.INFO)

    async with TrastCDPClient() as client:
        print(f"Подключено: {client.is_connected}")
        print(f"Авторизован: {client.is_logged_in}")
        print(f"URL: {client.url}")

        # Тестовый поиск
        result = await client.search_part("1920QK")
        print(f"Результат: {result}")


if __name__ == "__main__":
    asyncio.run(test_client())
