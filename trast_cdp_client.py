"""
CDP клиент для trast.ru - подключается к уже запущенному Chrome.

Использование:
1. Запустите start_chrome_debug.bat
2. async with TrastCDPClient() as client:
       result = await client.search_part("12345")
"""

import asyncio
import logging
import os
import re
from typing import Dict, Any, List, Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright
from base_browser_client import BaseBrowserClient
from config import TRAST_LOGIN, TRAST_PASSWORD, COOKIES_BACKUP_DIR

logger = logging.getLogger(__name__)

# Proxy for Trast (optional) - set TRAST_PROXY=http://user:pass@host:port
TRAST_PROXY = os.getenv("TRAST_PROXY", "")


class TrastCDPClient(BaseBrowserClient):
    """CDP клиент для trast-zapchast.ru с авторизацией и keep-alive.

    Использует stealth-режим для обхода JS-challenge защиты.
    """

    SITE_NAME = "trast"
    BASE_URL = "https://trast-zapchast.ru"

    async def connect(self) -> bool:
        """Подключиться к браузеру со stealth настройками для обхода защиты."""
        try:
            self.playwright = await async_playwright().start()

            logger.info(f"[{self.SITE_NAME}] Запуск Chromium в stealth режиме")

            # Stealth launch args
            launch_args = [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled',  # Hide automation
                '--no-first-run',
                '--disable-infobars',
                '--window-size=1920,1080',
                '--start-maximized',
            ]

            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=launch_args
            )

            # Proxy settings
            proxy_config = None
            if TRAST_PROXY:
                logger.info(f"[{self.SITE_NAME}] Используем прокси: {TRAST_PROXY.split('@')[-1] if '@' in TRAST_PROXY else TRAST_PROXY}")
                proxy_config = {"server": TRAST_PROXY}

            # Stealth context with realistic fingerprint
            self.context = await self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                locale='ru-RU',
                timezone_id='Europe/Moscow',
                proxy=proxy_config,
                java_script_enabled=True,
                permissions=['geolocation'],
                color_scheme='light',
                extra_http_headers={
                    'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                    'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                    'sec-ch-ua-mobile': '?0',
                    'sec-ch-ua-platform': '"Windows"',
                }
            )
            logger.info(f"[{self.SITE_NAME}] Создан stealth контекст")

            # Anti-detection scripts
            await self.context.add_init_script("""
                // Remove webdriver property
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

                // Fix plugins
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5]
                });

                // Fix languages
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['ru-RU', 'ru', 'en-US', 'en']
                });

                // Fix permissions
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                        Promise.resolve({ state: Notification.permission }) :
                        originalQuery(parameters)
                );
            """)

            # Load cookies from backup
            await self._load_cookies_from_backup()

            # Create page
            self.page = await self.context.new_page()

            self.is_connected = True
            logger.info(f"[{self.SITE_NAME}] Подключение установлено (stealth режим)")

            # Navigate to site and wait for JS challenge
            await self._pass_js_challenge()

            # Check auth
            await self._ensure_authenticated()

            # Start keep-alive
            self._start_keep_alive()

            return True

        except Exception as e:
            logger.error(f"[{self.SITE_NAME}] Ошибка подключения: {e}")
            return False

    async def _pass_js_challenge(self) -> bool:
        """Пройти JS challenge защиту сайта."""
        try:
            logger.info(f"[{self.SITE_NAME}] Проходим JS challenge...")

            await self.page.goto(self.BASE_URL, wait_until='domcontentloaded', timeout=60000)

            # Wait for JS challenge to complete (page will reload)
            for _ in range(10):  # Max 10 attempts, 3 sec each
                await self.page.wait_for_timeout(3000)

                # Check if we're past the challenge
                content = await self.page.content()
                if 'js-challenge' not in content.lower() and 'jsch._jsChallenge' not in content:
                    logger.info(f"[{self.SITE_NAME}] JS challenge пройден!")
                    return True

                # Check for challenge script
                if 'Ваш браузер не смог пройти' in content:
                    logger.debug(f"[{self.SITE_NAME}] Ожидаем прохождения challenge...")
                    continue

            logger.warning(f"[{self.SITE_NAME}] JS challenge не пройден за отведённое время")
            return False

        except Exception as e:
            logger.error(f"[{self.SITE_NAME}] Ошибка прохождения JS challenge: {e}")
            return False

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
                logger.info(f"[trast] Пароль введён в поле: {password_field}")
            else:
                logger.error("[trast] Поле пароля не найдено")
                return False

            # Нажимаем кнопку входа в форме логина (не в форме поиска!)
            # Ищем кнопку внутри формы с полем логина
            submit_selectors = [
                # Кнопки внутри формы с полем user_login
                'form:has(input[name="user_login"]) button[type="submit"]',
                'form:has(input[name="user_login"]) input[type="submit"]',
                'form:has(input[name="user_login"]) button:has-text("Войти")',
                # Кнопки с текстом "Войти" (но не поиск)
                'button:has-text("Войти"):not(:has-text("Поиск"))',
                'input[value="Войти"]',
                'input[value="Вход"]',
                # Общие селекторы как fallback
                '.login-form button[type="submit"]',
                '.auth-form button[type="submit"]',
                '#login-form button[type="submit"]',
            ]

            submit_clicked = False
            for selector in submit_selectors:
                try:
                    locator = self.page.locator(selector)
                    if await locator.count() > 0:
                        await locator.first.click()
                        logger.info(f"[trast] Нажата кнопка: {selector}")
                        submit_clicked = True
                        break
                except Exception as e:
                    logger.debug(f"[trast] Селектор {selector} не сработал: {e}")
                    continue

            if not submit_clicked:
                # Попробуем нажать Enter в поле пароля
                logger.warning("[trast] Кнопка входа не найдена, нажимаем Enter в поле пароля")
                await self.page.locator('input[type="password"]').press("Enter")
                logger.info("[trast] Нажат Enter в поле пароля")

            # Ждём загрузки
            await self.page.wait_for_timeout(5000)

            # Логируем текущий URL для отладки
            logger.info(f"[trast] URL после логина: {self.page.url}")

            # Проверяем успешность
            if await self.check_auth():
                logger.info("[trast] Авторизация успешна!")
                # Сохраняем cookies
                await self._save_cookies_to_backup()
                return True
            else:
                logger.error("[trast] Авторизация не удалась")
                # Логируем что на странице
                try:
                    title = await self.page.title()
                    logger.error(f"[trast] Заголовок страницы: {title}")
                except:
                    pass
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
            # Формируем URL поиска (используем ?s= вместо /search/?query=)
            search_url = f"{self.BASE_URL}/?s={partnumber}"
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

    # Маппинг брендов: что ищем -> что должно быть в производителе
    BRAND_MAPPING = {
        'peugeot': ['peugeot-citroen', 'peugeot', 'citroen', 'psa'],
        'citroen': ['peugeot-citroen', 'citroen', 'peugeot', 'psa'],
        'toyota': ['toyota'],
        'honda': ['honda'],
        'nissan': ['nissan'],
        'ford': ['ford'],
        'vw': ['volkswagen', 'vw', 'vag'],
        'volkswagen': ['volkswagen', 'vw', 'vag'],
        'bmw': ['bmw'],
        'mercedes': ['mercedes', 'mercedes-benz', 'daimler'],
        'opel': ['opel', 'gm'],
        'renault': ['renault'],
        'hyundai': ['hyundai', 'kia', 'mobis'],
        'kia': ['kia', 'hyundai', 'mobis'],
    }

    def _matches_brand_filter(self, manufacturer: str, brand_filter: str) -> bool:
        """Проверить, соответствует ли производитель фильтру по бренду."""
        if not brand_filter or not manufacturer:
            return True

        brand_lower = brand_filter.lower().strip()
        manuf_lower = manufacturer.lower().strip()

        # Получаем список допустимых производителей для этого бренда
        allowed_manufacturers = self.BRAND_MAPPING.get(brand_lower, [brand_lower])

        # Проверяем, содержит ли производитель любой из допустимых вариантов
        for allowed in allowed_manufacturers:
            if allowed in manuf_lower:
                return True

        return False

    async def _extract_prices_and_brand(self, brand_filter: str = None) -> Dict[str, Any]:
        """Извлечь цены и бренд из результатов поиска."""
        prices = []
        brand = None
        total_count = 0
        filtered_count = 0

        try:
            # Ждём появления результатов
            await self.page.wait_for_timeout(2000)

            # Получаем чистый текст страницы
            plain_text = await self.page.inner_text('body')

            # Разбиваем на блоки товаров по паттерну "Производитель:"
            # Каждый блок содержит информацию о товаре
            product_blocks = re.split(r'(?=Производитель:)', plain_text)

            for block in product_blocks:
                if 'Производитель:' not in block:
                    continue

                total_count += 1

                # Извлекаем производителя
                manuf_match = re.search(r'Производитель:\s*([^\n₽]+)', block)
                if not manuf_match:
                    continue

                manufacturer = manuf_match.group(1).strip()

                # Если есть фильтр по бренду - проверяем соответствие
                if brand_filter:
                    if not self._matches_brand_filter(manufacturer, brand_filter):
                        logger.debug(f"[trast] Пропускаем производителя '{manufacturer}' (фильтр: {brand_filter})")
                        continue
                    logger.debug(f"[trast] Производитель '{manufacturer}' соответствует фильтру '{brand_filter}'")

                filtered_count += 1

                # Сохраняем бренд первого подходящего товара
                if not brand:
                    brand = manufacturer

                # Извлекаем цену из этого блока
                price_match = re.search(r'([\d\s\xa0]{1,15})\s*₽', block)
                if price_match:
                    try:
                        price_str = price_match.group(1).replace(" ", "").replace("\xa0", "").strip()
                        if price_str:
                            val = float(price_str)
                            if 100 < val < 500000:
                                prices.append(val)
                                logger.debug(f"[trast] Цена {val}₽ от {manufacturer}")
                    except ValueError:
                        pass

            # Если не нашли блоки с производителем, пробуем простой поиск цен
            if not prices and not brand_filter:
                all_prices = re.findall(r'([\d\s\xa0]{1,15})\s*₽', plain_text)
                for price_str in all_prices:
                    try:
                        price_str = price_str.replace(" ", "").replace("\xa0", "").strip()
                        if price_str:
                            val = float(price_str)
                            if 100 < val < 500000:
                                prices.append(val)
                    except ValueError:
                        pass

        except Exception as e:
            logger.debug(f"[trast] Ошибка извлечения данных: {e}")

        if brand_filter:
            logger.info(f"[trast] Отфильтровано по бренду '{brand_filter}': {filtered_count}/{total_count} товаров")

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
