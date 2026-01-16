"""
Базовый класс для браузерных клиентов с подключением через Chrome DevTools Protocol.

Функции:
- Подключение к уже запущенному Chrome через CDP (remote debugging port 9222)
- Проверка авторизации и автологин
- Keep-alive для поддержания сессии
- Backup/restore cookies в файл
"""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Playwright,
    CDPSession,
)

from config import BASEDIR, CHROME_CDP_ENDPOINT, COOKIES_BACKUP_DIR, KEEP_ALIVE_INTERVAL

logger = logging.getLogger(__name__)


class BaseBrowserClient(ABC):
    """
    Базовый класс для браузерных парсеров с подключением к Chrome через CDP.

    Для использования:
    1. Запустите Chrome с флагом --remote-debugging-port=9222 (start_chrome_debug.bat)
    2. Создайте экземпляр клиента и вызовите connect()
    3. Клиент автоматически проверит авторизацию и выполнит логин при необходимости
    """

    # Переопределите в наследниках
    SITE_NAME: str = "base"
    BASE_URL: str = ""
    CDP_ENDPOINT: str = CHROME_CDP_ENDPOINT
    KEEP_ALIVE_INTERVAL_SEC: int = KEEP_ALIVE_INTERVAL
    COOKIES_DIR: Path = COOKIES_BACKUP_DIR

    def __init__(self) -> None:
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.cdp_session: Optional[CDPSession] = None
        self.is_connected: bool = False
        self.is_logged_in: bool = False
        self._keep_alive_task: Optional[asyncio.Task] = None

    @property
    def cookies_file(self) -> Path:
        """Путь к файлу с куками для этого сайта."""
        return self.COOKIES_DIR / f"{self.SITE_NAME}_cookies.json"

    # ========== Подключение к Chrome ==========

    async def connect(self) -> bool:
        """
        Подключиться к запущенному Chrome через CDP.

        Returns:
            True если подключение и авторизация успешны
        """
        try:
            logger.info(f"[{self.SITE_NAME}] Подключение к Chrome CDP: {self.CDP_ENDPOINT}")

            self.playwright = await async_playwright().start()

            # Подключаемся к существующему Chrome
            self.browser = await self.playwright.chromium.connect_over_cdp(
                self.CDP_ENDPOINT,
                timeout=30000
            )

            # Получаем существующий контекст или создаём новый
            contexts = self.browser.contexts
            if contexts:
                self.context = contexts[0]
                logger.info(f"[{self.SITE_NAME}] Использую существующий контекст")
            else:
                self.context = await self.browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
                logger.info(f"[{self.SITE_NAME}] Создан новый контекст")

                # Пробуем загрузить cookies из backup
                await self._load_cookies_from_backup()

            # Ищем существующую страницу с нашим сайтом или создаём новую
            self.page = await self._find_or_create_page()

            self.is_connected = True
            logger.info(f"[{self.SITE_NAME}] Подключение установлено")

            # Проверяем авторизацию
            await self._ensure_authenticated()

            # Запускаем keep-alive
            self._start_keep_alive()

            return True

        except Exception as e:
            logger.error(f"[{self.SITE_NAME}] Ошибка подключения к Chrome: {e}")
            logger.error(f"[{self.SITE_NAME}] Убедитесь, что Chrome запущен с флагом --remote-debugging-port=9222")
            return False

    async def _find_or_create_page(self) -> Page:
        """Найти страницу с нашим сайтом или создать новую."""
        # Ищем страницу с нашим URL
        for page in self.context.pages:
            if self.BASE_URL in page.url:
                logger.info(f"[{self.SITE_NAME}] Найдена страница: {page.url}")
                return page

        # Создаём новую страницу
        page = await self.context.new_page()
        logger.info(f"[{self.SITE_NAME}] Создана новая страница")
        return page

    async def disconnect(self) -> None:
        """Отключиться от Chrome (не закрывает браузер)."""
        logger.info(f"[{self.SITE_NAME}] Отключение...")

        # Останавливаем keep-alive
        self._stop_keep_alive()

        # Сохраняем cookies перед отключением
        await self._save_cookies_to_backup()

        # Отключаемся (но не закрываем Chrome)
        if self.playwright:
            await self.playwright.stop()

        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.is_connected = False

        logger.info(f"[{self.SITE_NAME}] Отключено")

    async def __aenter__(self) -> "BaseBrowserClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.disconnect()

    # ========== Авторизация ==========

    async def _ensure_authenticated(self) -> bool:
        """Проверить авторизацию и выполнить логин при необходимости."""
        logger.info(f"[{self.SITE_NAME}] Проверка авторизации...")

        # Переходим на сайт если ещё не там
        if self.BASE_URL not in self.page.url:
            await self.page.goto(self.BASE_URL, wait_until='domcontentloaded', timeout=60000)
            await self.page.wait_for_timeout(2000)

        # Проверяем авторизацию
        if await self.check_auth():
            self.is_logged_in = True
            logger.info(f"[{self.SITE_NAME}] Уже авторизован")
            return True

        # Выполняем автологин
        logger.info(f"[{self.SITE_NAME}] Требуется авторизация, выполняю логин...")

        if await self.auto_login():
            self.is_logged_in = True
            # Сохраняем cookies после успешного логина
            await self._save_cookies_to_backup()
            logger.info(f"[{self.SITE_NAME}] Авторизация успешна")
            return True
        else:
            self.is_logged_in = False
            logger.error(f"[{self.SITE_NAME}] Не удалось авторизоваться")
            return False

    @abstractmethod
    async def check_auth(self) -> bool:
        """
        Проверить, авторизован ли пользователь.

        Реализуйте в наследнике: проверьте наличие элементов,
        характерных для авторизованного пользователя.

        Returns:
            True если пользователь авторизован
        """
        pass

    @abstractmethod
    async def auto_login(self) -> bool:
        """
        Выполнить автоматический логин.

        Реализуйте в наследнике: заполните форму логина и отправьте.
        Credentials берите из config.py.

        Returns:
            True если логин успешен
        """
        pass

    # ========== Keep-Alive ==========

    def _start_keep_alive(self) -> None:
        """Запустить фоновую задачу keep-alive."""
        if self._keep_alive_task is None or self._keep_alive_task.done():
            self._keep_alive_task = asyncio.create_task(self._keep_alive_loop())
            logger.info(f"[{self.SITE_NAME}] Keep-alive запущен (интервал: {self.KEEP_ALIVE_INTERVAL_SEC}с)")

    def _stop_keep_alive(self) -> None:
        """Остановить фоновую задачу keep-alive."""
        if self._keep_alive_task and not self._keep_alive_task.done():
            self._keep_alive_task.cancel()
            logger.info(f"[{self.SITE_NAME}] Keep-alive остановлен")

    async def _keep_alive_loop(self) -> None:
        """Цикл keep-alive: делает лёгкий запрос каждые N минут."""
        while True:
            try:
                await asyncio.sleep(self.KEEP_ALIVE_INTERVAL_SEC)

                if not self.is_connected or not self.page:
                    break

                await self.keep_alive()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[{self.SITE_NAME}] Ошибка keep-alive: {e}")

    async def keep_alive(self) -> None:
        """
        Выполнить лёгкий запрос для поддержания сессии.

        По умолчанию делает HEAD-запрос к BASE_URL.
        Переопределите для специфичной логики.
        """
        try:
            logger.debug(f"[{self.SITE_NAME}] Keep-alive ping...")

            # Простой способ - обновить страницу или сделать лёгкий fetch
            # Используем evaluate для минимального запроса
            await self.page.evaluate(f'''
                fetch("{self.BASE_URL}", {{method: "HEAD", credentials: "include"}})
                    .catch(() => {{}});
            ''')

            logger.debug(f"[{self.SITE_NAME}] Keep-alive OK")

        except Exception as e:
            logger.warning(f"[{self.SITE_NAME}] Keep-alive ошибка: {e}")

    # ========== Cookies Backup/Restore ==========

    async def _save_cookies_to_backup(self) -> bool:
        """Сохранить cookies в файл."""
        try:
            if not self.context:
                return False

            # Создаём директорию если нет
            self.COOKIES_DIR.mkdir(parents=True, exist_ok=True)

            # Получаем cookies
            cookies = await self.context.cookies()

            if not cookies:
                logger.warning(f"[{self.SITE_NAME}] Нет cookies для сохранения")
                return False

            # Сохраняем с метаданными
            backup_data = {
                "site": self.SITE_NAME,
                "saved_at": datetime.now().isoformat(),
                "cookies": cookies
            }

            with open(self.cookies_file, 'w', encoding='utf-8') as f:
                json.dump(backup_data, f, ensure_ascii=False, indent=2)

            logger.info(f"[{self.SITE_NAME}] Cookies сохранены: {self.cookies_file} ({len(cookies)} шт.)")
            return True

        except Exception as e:
            logger.error(f"[{self.SITE_NAME}] Ошибка сохранения cookies: {e}")
            return False

    async def _load_cookies_from_backup(self) -> bool:
        """Загрузить cookies из файла."""
        try:
            if not self.cookies_file.exists():
                logger.info(f"[{self.SITE_NAME}] Файл cookies не найден: {self.cookies_file}")
                return False

            with open(self.cookies_file, 'r', encoding='utf-8') as f:
                backup_data = json.load(f)

            cookies = backup_data.get("cookies", [])
            if not cookies:
                return False

            # Загружаем cookies в контекст
            await self.context.add_cookies(cookies)

            saved_at = backup_data.get("saved_at", "unknown")
            logger.info(f"[{self.SITE_NAME}] Cookies загружены из backup ({len(cookies)} шт., сохранены: {saved_at})")
            return True

        except Exception as e:
            logger.error(f"[{self.SITE_NAME}] Ошибка загрузки cookies: {e}")
            return False

    async def save_cookies(self) -> bool:
        """Публичный метод для сохранения cookies."""
        return await self._save_cookies_to_backup()

    async def load_cookies(self) -> bool:
        """Публичный метод для загрузки cookies."""
        return await self._load_cookies_from_backup()

    # ========== Утилиты ==========

    async def navigate(self, url: str, wait_until: str = 'domcontentloaded', timeout: int = 60000) -> None:
        """Перейти по URL."""
        await self.page.goto(url, wait_until=wait_until, timeout=timeout)

    async def wait(self, ms: int) -> None:
        """Подождать указанное время в миллисекундах."""
        await self.page.wait_for_timeout(ms)

    @property
    def url(self) -> str:
        """Текущий URL страницы."""
        return self.page.url if self.page else ""
