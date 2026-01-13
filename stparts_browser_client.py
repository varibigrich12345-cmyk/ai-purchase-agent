"""
Playwright клиент для stparts.ru с авторизацией
Версия: 2.0 - С оптовыми ценами
"""

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
    Клиент Playwright для stparts.ru с авторизацией.
    Получает индивидуальные оптовые цены после логина.
    """
    BASE_URL = "https://stparts.ru"
    
    def __init__(self, playwright: Playwright, headless: bool = False) -> None:
        self.playwright = playwright
        self.headless = headless
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.is_logged_in = False

    async def __aenter__(self) -> "STPartsBrowserClient":
        logger.info("🚀 Запуск браузера для stparts.ru...")
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=['--disable-blink-features=AutomationControlled']
        )
        self.page = await self.browser.new_page()
        logger.info("✅ Браузер stparts запущен")
        
        # Сразу авторизуемся при старте
        await self.login_to_site()
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
        Авторизация в STparts для получения оптовых цен.
        ВАЖНО: После логина доступны индивидуальные цены компании.
        """
        assert self.page is not None
        page = self.page

        login_url = f"{self.BASE_URL}/login"
        logger.info(f"🔐 [STPARTS] Авторизация: {login_url}")
        
        try:
            await page.goto(login_url, wait_until="networkidle", timeout=15000)
            
            # Креды из файла (в продакшене используй env-переменные)
            username = "89297748866@mail.ru"
            password = "SSSsss@12345678"
            
            logger.info("✍️ [STPARTS] Ввод логина и пароля...")
            await page.get_by_placeholder("E-mail").fill(username)
            await page.get_by_placeholder("Пароль").fill(password)
            await page.get_by_role("button", name="Войти").click()
            
            # Ждем завершения логина (проверяем исчезновение формы)
            await page.wait_for_timeout(2000)
            
            # Проверяем успешность логина
            current_url = page.url
            if "/login" not in current_url:
                self.is_logged_in = True
                logger.info("✅ [STPARTS] Авторизация успешна! Доступны оптовые цены")
            else:
                logger.warning("⚠️ [STPARTS] Возможно, логин не прошёл (все еще на /login)")
                self.is_logged_in = False
                
        except Exception as e:
            logger.error(f"❌ [STPARTS] Ошибка авторизации: {e}")
            self.is_logged_in = False

    async def search_part_with_retry(
        self,
        part_number: str,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        """Поиск с повторными попытками"""
        last_error: Optional[Exception] = None
        
        for attempt in range(1, max_retries + 1):
            logger.info(f"🔍 [STPARTS] Попытка {attempt}/{max_retries}: {part_number}")
            try:
                return await self.search_part(part_number)
            except PlaywrightTimeout as e:
                last_error = e
                logger.warning(f"⏰ [STPARTS] Таймаут для {part_number}: {e}")
            except Exception as e:
                last_error = e
                logger.error(f"💥 [STPARTS] Ошибка при поиске {part_number}: {e}")
            
            if attempt < max_retries:
                await asyncio.sleep(2 * attempt)
        
        logger.error(f"❌ [STPARTS] Не удалось получить результат для {part_number}")
        return {
            "status": f"error: {last_error}",
            "prices": {"min": None, "avg": None},
            "url": None,
        }

    async def search_part(self, part_number: str) -> Dict[str, Any]:
        """
        Выполнить поиск детали на stparts.ru.
        Возвращает:
        {
            "status": "success"|"not_found"|"error: ...",
            "prices": {"min": float|None, "avg": float|None},
            "url": str|None
        }
        """
        assert self.page is not None
        page = self.page

        # Используем прямую ссылку для поиска
        search_url = f"{self.BASE_URL}/search"
        logger.info(f"🌐 [STPARTS] Переход: {search_url}")
        await page.goto(search_url, wait_until="networkidle", timeout=15000)

        # Ввод артикула
        logger.info(f"⌨️ [STPARTS] Ввод артикула: {part_number}")
        search_input = page.get_by_placeholder("Артикул или наименование")
        await search_input.fill(part_number)
        await search_input.press("Enter")

        # Ждём результатов
        logger.info("⏳ [STPARTS] Ожидание результатов...")
        await page.wait_for_timeout(2000)

        # Кликаем по "Цены и аналоги" если есть
        try:
            link = page.get_by_role("link", name="Цены и аналоги").first
            if await link.is_visible(timeout=3000):
                logger.info("🖱 [STPARTS] Клик по 'Цены и аналоги'")
                await link.click()
                await page.wait_for_timeout(2000)
        except Exception:
            logger.info("ℹ️ [STPARTS] 'Цены и аналоги' не требуется")

        # Парсим цены
        prices = await self.extract_prices(page)
        
        if not prices:
            logger.warning(f"⚠️ [STPARTS] Цены не найдены для {part_number}")
            return {
                "status": "not_found",
                "prices": {"min": None, "avg": None},
                "url": page.url,
            }

        min_price = min(prices)
        avg_price = round(sum(prices) / len(prices), 2)
        logger.info(f"📊 [STPARTS] Найдено цен: {len(prices)}, min={min_price}₽, avg={avg_price}₽")
        
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
        Извлекает ОПТОВЫЕ цены из таблицы результатов.
        Использует устойчивые селекторы.
        """
        prices: List[float] = []

        # Проверяем наличие таблицы
        table = page.locator("#searchResultsTable")
        try:
            await table.wait_for(state="visible", timeout=10000)
        except PlaywrightTimeout:
            logger.warning("⚠️ [STPARTS] Таблица #searchResultsTable не появилась")
            return prices

        # Получаем все строки таблицы
        rows = table.locator("tbody tr")
        count = await rows.count()
        logger.info(f"📋 [STPARTS] Найдено строк: {count}")

        # Парсим каждую строку
        for i in range(count):
            row = rows.nth(i)
            cells = row.locator("td")
            cell_count = await cells.count()
            
            # Проходим по всем ячейкам строки
            for j in range(cell_count):
                cell = cells.nth(j)
                text = (await cell.inner_text()).strip()
                
                if not text:
                    continue
                
                # Ищем паттерн цены: "1234р" или "1 234 р."
                match = re.search(r"(\d[\d\s]*)\s*р", text, re.IGNORECASE)
                if match:
                    raw = match.group(1)
                    value_str = raw.replace(" ", "").replace("\xa0", "")
                    try:
                        value = float(value_str)
                        # Фильтр разумных значений для автозапчастей
                        if 500 < value < 100000:
                            prices.append(value)
                            logger.debug(f"💰 [STPARTS] Цена: {value}₽")
                    except ValueError:
                        continue

        # Убираем дубликаты
        prices = list(set(prices))
        
        if prices:
            logger.info(f"✅ [STPARTS] Уникальных цен: {len(prices)}")
        
        return prices
