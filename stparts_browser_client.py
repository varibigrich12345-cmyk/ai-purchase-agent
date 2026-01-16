"""
Playwright клиент для stparts.ru с авторизацией
"""

import asyncio
import logging
import re
from typing import Dict, Any, List, Optional
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeout,
)
from playwright_stealth import stealth_async

from config import STPARTS_LOGIN, STPARTS_PASSWORD

logger = logging.getLogger(__name__)


class STPartsBrowserClient:
    """
    Клиент Playwright для stparts.ru с авторизацией.
    """

    BASE_URL = "https://stparts.ru"

    def __init__(self, playwright: Playwright, headless: bool = False) -> None:
        self.playwright = playwright
        self.headless = headless
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.is_logged_in = False

    async def __aenter__(self) -> "STPartsBrowserClient":
        logger.info("Запуск браузера для stparts.ru...")

        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-features=AsyncDns',
            ]
        )

        self.context = await self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            bypass_csp=True,
            ignore_https_errors=True
        )

        self.page = await self.context.new_page()

        # Применяем stealth режим для обхода защиты от ботов
        await stealth_async(self.page)
        logger.info("Браузер stparts запущен (stealth mode)")

        await self.login()

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        logger.info("Закрытие браузера stparts...")

        try:
            if self.page:
                await self.page.close()
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            logger.info("Браузер stparts закрыт")
        except Exception as e:
            logger.error(f"Ошибка при закрытии браузера: {e}")

    async def login(self) -> bool:
        """Авторизация на stparts.ru"""
        try:
            logger.info("Попытка авторизации на stparts.ru...")

            # Сначала заходим на главную - сайт может потребовать проверку браузера
            logger.info("Переход на главную страницу для прохождения проверки...")
            await self.page.goto(self.BASE_URL, wait_until='networkidle', timeout=60000)
            await self.page.wait_for_timeout(5000)

            # Теперь переходим на страницу логина
            login_url = f"{self.BASE_URL}/login"
            await self.page.goto(login_url, wait_until='networkidle', timeout=60000)
            await self.page.wait_for_timeout(3000)

            # Ждём появления поля email (пробуем разные селекторы)
            email_selectors = [
                'input[placeholder*="mail"]',
                'input[placeholder*="Mail"]',
                'input[type="email"]',
                'input[name="email"]',
                'input[name="login"]',
            ]

            email_field = None
            for selector in email_selectors:
                try:
                    await self.page.wait_for_selector(selector, timeout=5000)
                    email_field = selector
                    logger.info(f"Найдено поле email: {selector}")
                    break
                except:
                    continue

            if not email_field:
                logger.error("Не найдено поле email. Проверяю страницу...")
                logger.info(f"Текущий URL: {self.page.url}")
                page_content = await self.page.content()

                # Если мы на странице проверки браузера - ждём дольше
                if 'Access denied' in page_content or 'browser' in page_content.lower():
                    logger.info("Обнаружена проверка браузера, ждём 15 сек...")
                    await self.page.wait_for_timeout(15000)
                    # Попробуем перейти снова
                    await self.page.goto(login_url, wait_until='networkidle', timeout=60000)
                    await self.page.wait_for_timeout(5000)

                # Логируем что видим на странице
                logger.info(f"Контент страницы (первые 300 символов): {page_content[:300]}")
                return False

            # Заполняем форму (пробуем разные способы)
            try:
                await self.page.get_by_placeholder("E-mail").fill(STPARTS_LOGIN)
            except:
                await self.page.fill(email_field, STPARTS_LOGIN)

            # Заполняем пароль
            password_selectors = [
                'input[placeholder*="ароль"]',
                'input[type="password"]',
                'input[name="password"]',
            ]
            password_filled = False
            for selector in password_selectors:
                try:
                    await self.page.fill(selector, STPARTS_PASSWORD)
                    password_filled = True
                    break
                except:
                    continue

            if not password_filled:
                try:
                    await self.page.get_by_placeholder("Пароль").fill(STPARTS_PASSWORD)
                except:
                    logger.error("Не удалось заполнить пароль")
                    return False

            logger.info(f"Логин введён: {STPARTS_LOGIN}")

            # Нажимаем кнопку "Войти"
            try:
                await self.page.get_by_role("button", name="Войти").click()
            except:
                # Пробуем другие варианты
                try:
                    await self.page.click('button[type="submit"]')
                except:
                    await self.page.press(email_field, "Enter")

            # Ждём загрузки после логина
            await self.page.wait_for_timeout(5000)

            # Проверяем успешность логина
            if '/login' not in self.page.url:
                self.is_logged_in = True
                logger.info("Авторизация успешна!")
                return True
            else:
                logger.error("Авторизация не прошла (остались на странице логина)")
                return False

        except Exception as e:
            logger.error(f"Ошибка авторизации: {e}")
            return False

    async def search_part_with_retry(self, partnumber: str, max_retries: int = 3) -> Dict[str, Any]:
        """Поиск запчасти с повторными попытками."""
        for attempt in range(1, max_retries + 1):
            logger.info(f"Попытка {attempt}/{max_retries}: {partnumber}")
            try:
                result = await self.search_part(partnumber)

                if result.get('status') == 'success' and result.get('prices', {}).get('min'):
                    logger.info(f"Успех! min={result['prices']['min']}, avg={result['prices']['avg']}")
                    return result
                else:
                    logger.warning(f"Нет цен на попытке {attempt}")

            except Exception as e:
                logger.error(f"Ошибка на попытке {attempt}: {e}")

                if attempt == max_retries:
                    return {
                        'partnumber': partnumber,
                        'status': 'error',
                        'prices': {'min': None, 'avg': None},
                        'url': self.page.url if self.page else None,
                        'error': str(e)
                    }

            # Задержка перед повтором
            if attempt < max_retries:
                await asyncio.sleep(2 * attempt)

        # Если все попытки исчерпаны
        return {
            'partnumber': partnumber,
            'status': 'not_found',
            'prices': {'min': None, 'avg': None},
            'url': self.page.url if self.page else None
        }

    async def search_part(self, partnumber: str) -> Dict[str, Any]:
        """Основной метод поиска запчасти."""
        page = self.page

        # Переход на страницу поиска
        await page.goto(f"{self.BASE_URL}/search", wait_until='networkidle', timeout=60000)
        await page.wait_for_timeout(3000)

        # Пробуем разные селекторы для поля поиска
        search_selectors = [
            'input[placeholder*="Артикул"]',
            'input[placeholder*="артикул"]',
            'input[placeholder*="наименование"]',
            'input[name="query"]',
            'input[name="search"]',
            'input[name="q"]',
            'input[type="search"]',
            '#search-input',
            '.search-input',
        ]

        search_field = None
        for selector in search_selectors:
            try:
                if await page.locator(selector).count() > 0:
                    search_field = selector
                    logger.info(f"Найдено поле поиска: {selector}")
                    break
            except:
                continue

        if not search_field:
            # Логируем что на странице
            page_content = await page.content()
            logger.info(f"Поле поиска не найдено. URL: {page.url}")
            logger.info(f"Контент страницы (первые 500 символов): {page_content[:500]}")

            # Если страница с проверкой - ждём
            if 'Access denied' in page_content:
                logger.info("Обнаружена проверка, ждём 15 сек...")
                await page.wait_for_timeout(15000)
                await page.goto(f"{self.BASE_URL}/search", wait_until='networkidle', timeout=60000)
                await page.wait_for_timeout(3000)

            # Пробуем через get_by_placeholder
            try:
                search_input = page.get_by_placeholder("Артикул или наименование")
                await search_input.fill(partnumber)
                await search_input.press("Enter")
            except Exception as e:
                logger.error(f"Не найдено поле поиска: {e}")
                return {
                    'partnumber': partnumber,
                    'status': 'error',
                    'prices': {'min': None, 'avg': None},
                    'url': page.url,
                    'error': 'Поле поиска не найдено'
                }
        else:
            await page.fill(search_field, partnumber)
            await page.press(search_field, "Enter")

        logger.info(f"Ввели артикул: {partnumber}")

        # Ждём загрузки результатов
        await page.wait_for_timeout(3000)

        # Пробуем нажать на "Цены и аналоги" если есть
        try:
            link = page.get_by_role("link", name="Цены и аналоги").first
            if await link.is_visible(timeout=3000):
                await link.click()
                await page.wait_for_timeout(2000)
        except:
            pass

        # Извлекаем цены
        prices = await self._extract_prices()

        if not prices:
            return {
                'partnumber': partnumber,
                'status': 'not_found',
                'prices': {'min': None, 'avg': None},
                'url': page.url
            }

        return {
            'partnumber': partnumber,
            'status': 'success',
            'prices': {
                'min': min(prices),
                'avg': round(sum(prices) / len(prices), 2)
            },
            'url': page.url
        }

    async def _extract_prices(self) -> List[float]:
        """Извлекает цены из таблицы результатов."""
        prices = []
        page = self.page

        # Таблица результатов на stparts.ru
        table = page.locator("#searchResultsTable")

        try:
            await table.wait_for(state="visible", timeout=10000)
            rows = table.locator("tbody tr")
            count = await rows.count()

            logger.info(f"Найдено строк: {count}")

            for i in range(count):
                cells = rows.nth(i).locator("td")
                cell_count = await cells.count()

                for j in range(cell_count):
                    text = (await cells.nth(j).inner_text()).strip()

                    # Ищем цены (формат: "3 500 р" или "3500р")
                    match = re.search(r"(\d[\d\s]*)\s*р", text, re.I)
                    if match:
                        try:
                            price_str = match.group(1).replace(" ", "").replace("\xa0", "")
                            val = float(price_str)

                            # Фильтр разумных цен (500-100000)
                            if 500 < val < 100000:
                                prices.append(val)
                        except ValueError:
                            pass

        except Exception as e:
            logger.debug(f"Ошибка извлечения цен: {e}")

        # Убираем дубликаты
        unique_prices = list(set(prices))

        if unique_prices:
            logger.info(f"Найдено {len(unique_prices)} уникальных цен")

        return unique_prices
