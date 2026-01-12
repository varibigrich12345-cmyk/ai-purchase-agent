# stparts_browser_client.py
import asyncio
import logging
import re
from typing import Dict, Any, List, Optional

from playwright.async_api import (
    Browser,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeout,
)

logger = logging.getLogger(__name__)


class STPartsBrowserClient:
    """
    Клиент Playwright для stparts.ru (только Locator API).
    """

    BASE_URL = "https://stparts.ru"

    def __init__(self, playwright: Playwright, headless: bool = False) -> None:
        self.playwright = playwright
        self.headless = headless
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None

    async def __aenter__(self) -> "STPartsBrowserClient":
        logger.info("🚀 Запуск браузера для stparts.ru...")
        self.browser = await self.playwright.chromium.launch(headless=self.headless)
        self.page = await self.browser.new_page()
        logger.info("✅ Браузер запущен (stparts)")
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        logger.info("🧹 Закрытие браузера stparts...")
        if self.page:
            await self.page.close()
        if self.browser:
            await self.browser.close()
        logger.info("✅ Браузер stparts закрыт")

    async def login_to_site(self) -> None:
        """
        Логин в личный кабинет STparts.
        Пара логина/пароля должна быть заранее захардкожена или загружена из окружения.
        """
        assert self.page is not None
        page = self.page

        login_url = f"{self.BASE_URL}/login"
        logger.info(f"🌐 Переход на страницу логина: {login_url}")
        await page.goto(login_url, wait_until="networkidle")

        # TODO: замените на реальные креды
        username = "89297748866@mail.ru"
        password = "SSSsss@12345678"

        logger.info("✍️ Ввод логина и пароля...")
        await page.get_by_placeholder("E-mail").fill(username)
        await page.get_by_placeholder("Пароль").fill(password)
        await page.get_by_role("button", name="Войти").click()

        # Дождаться, пока исчезнет форма логина или появится элемент личного кабинета
        await page.wait_for_timeout(1000)
        logger.info("✅ Авторизация stparts: попытка завершена")

    async def search_part_with_retry(
        self,
        part_number: str,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        last_error: Optional[Exception] = None
        for attempt in range(1, max_retries + 1):
            logger.info(f"🔍 [STPARTS] Попытка {attempt}/{max_retries}: {part_number}")
            try:
                return await self.search_part(part_number)
            except PlaywrightTimeout as e:
                last_error = e
                logger.warning(f"⏰ Таймаут stparts для {part_number}: {e}")
            except Exception as e:
                last_error = e
                logger.exception(f"💥 Ошибка stparts при поиске {part_number}: {e}")

            await asyncio.sleep(2 * attempt)

        logger.error(f"❌ [STPARTS] Не удалось получить результат для {part_number}")
        return {
            "status": f"error: {last_error}",
            "prices": {"min": None, "avg": None},
            "url": None,
        }

    async def search_part(self, part_number: str) -> Dict[str, Any]:
        """
        Выполнить поиск детали на stparts.ru и вернуть цены.
        Возвращает:
        {
            "status": "success"|"not_found"|"error: ...",
            "prices": {"min": float|None, "avg": float|None},
            "url": str|None
        }
        """
        assert self.page is not None
        page = self.page

        search_url = f"{self.BASE_URL}/search"
        logger.info(f"🌐 [STPARTS] Переход: {search_url}")
        await page.goto(search_url, wait_until="networkidle")

        # Ввод артикула
        logger.info(f"⌨️ [STPARTS] Ввод артикула: {part_number}")
        search_input = page.get_by_placeholder("Артикул или наименование")
        await search_input.fill(part_number)
        await search_input.press("Enter")

        # Ждём результатов и таблицу searchResultsTable
        logger.info("⏳ [STPARTS] Ожидание таблицы результатов...")
        await page.wait_for_timeout(1500)

        # Кликаем по ссылке "Цены и аналоги" если она нужна для открытия таблицы
        try:
            link = page.get_by_role("link", name="Цены и аналоги").first
            if await link.is_visible():
                logger.info("🖱 [STPARTS] Клик по 'Цены и аналоги'")
                await link.click()
                await page.wait_for_timeout(1500)
        except Exception:
            logger.info("ℹ️ [STPARTS] 'Цены и аналоги' не найдена или не нужна")

        prices = await self.extract_prices(page)
        if not prices:
            logger.warning(f"⚠️ [STPARTS] Цены не найдены для {part_number}")
            return {
                "status": "not_found",
                "prices": {"min": None, "avg": None},
                "url": page.url,
            }

        min_price = min(prices)
        avg_price = sum(prices) / len(prices)
        logger.info(f"📊 [STPARTS] Найдено цен: {len(prices)}, min={min_price}, avg={avg_price}")

        return {
            "status": "success",
            "prices": {
                "min": min_price,
                "avg": avg_price,
            },
            "url": page.url,
        }

    async def extract_prices(self, page: Page) -> List[float]:
        """
        Извлекает цены из таблицы результатов.
        Использует только Locator API.
        """
        prices: List[float] = []

        # Основная таблица результатов по id
        table = page.locator("#searchResultsTable")
        if not await table.is_visible():
            logger.warning("⚠️ [STPARTS] Таблица #searchResultsTable не видна")
            return prices

        rows = table.locator("tbody tr")
        count = await rows.count()
        logger.info(f"📋 [STPARTS] Найдено строк в таблице: {count}")

        for i in range(count):
            row = rows.nth(i)

            # предположим, что цена в одной из последних колонок
            cells = row.locator("td")
            cell_count = await cells.count()
            if cell_count == 0:
                continue

            # берём все ячейки, ищем в тексте паттерн цены
            for j in range(cell_count):
                cell = cells.nth(j)
                text = (await cell.inner_text()).strip()
                if not text:
                    continue

                # Лог для отладки
                logger.debug(f"🔍 [STPARTS] Ячейка {i}:{j} -> '{text}'")

                # Извлекаем число формата "1 234р." или "1 234 р."
                match = re.search(r"(\d[\d\s]*)\s*р", text)
                if match:
                    raw = match.group(1)
                    value_str = raw.replace(" ", "").replace("\xa0", "")
                    try:
                        value = float(value_str)
                        if value > 0:
                            prices.append(value)
                            logger.debug(f"💰 [STPARTS] Цена: {value}")
                    except ValueError:
                        logger.debug(f"🚫 [STPARTS] Не удалось преобразовать '{value_str}' в число")

        return prices
