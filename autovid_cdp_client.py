"""
CDP клиент для auto-vid.com - подключается к уже запущенному Chrome.

Использование:
1. Запустите start_chrome_debug.bat
2. async with AutoVidCDPClient() as client:
       result = await client.search_part("12345")

Особенности авторизации:
- URL: https://auto-vid.com/login-for-wholesale-customers/
- Перед входом ОБЯЗАТЕЛЬНО поставить галочку "Я соглашаюсь с политикой конфиденциальности"
"""

import asyncio
import logging
import re
from typing import Dict, Any

from playwright.async_api import async_playwright
from base_browser_client import BaseBrowserClient
from config import AUTOVID_LOGIN, AUTOVID_PASSWORD, COOKIES_BACKUP_DIR

logger = logging.getLogger(__name__)


class AutoVidCDPClient(BaseBrowserClient):
    """CDP клиент для auto-vid.com с авторизацией и keep-alive."""

    SITE_NAME = "autovid"
    BASE_URL = "https://auto-vid.com"
    LOGIN_URL = "https://auto-vid.com/login-for-wholesale-customers/"

    async def connect(self) -> bool:
        """Подключиться к браузеру."""
        try:
            self.playwright = await async_playwright().start()

            logger.info(f"[{self.SITE_NAME}] Запуск Chromium в headless режиме")

            launch_args = [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled',
                '--no-first-run',
                '--disable-infobars',
                '--window-size=1920,1080',
            ]

            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=launch_args
            )

            # Создаём контекст с реалистичными настройками
            self.context = await self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                locale='ru-RU',
                timezone_id='Europe/Moscow',
                java_script_enabled=True,
                extra_http_headers={
                    'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
                }
            )
            logger.info(f"[{self.SITE_NAME}] Создан контекст браузера")

            # Anti-detection
            await self.context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            """)

            # Load cookies from backup
            await self._load_cookies_from_backup()

            # Create page
            self.page = await self.context.new_page()

            self.is_connected = True
            logger.info(f"[{self.SITE_NAME}] Подключение установлено (headless режим)")

            # Check and ensure auth
            await self._ensure_authenticated()

            # Start keep-alive
            self._start_keep_alive()

            return True

        except Exception as e:
            logger.error(f"[{self.SITE_NAME}] Ошибка подключения: {e}")
            return False

    async def check_auth(self) -> bool:
        """Проверить, авторизован ли пользователь на auto-vid.com."""
        try:
            # Переходим на главную страницу
            if self.BASE_URL not in self.page.url:
                await self.page.goto(self.BASE_URL, wait_until='domcontentloaded', timeout=30000)
                await self.page.wait_for_timeout(2000)

            # Проверяем признаки авторизации
            auth_indicators = [
                'text="Выход"',
                'text="Выйти"',
                'text="Личный кабинет"',
                'text="Мой аккаунт"',
                '[href*="logout"]',
                '[href*="my-account"]',
                '.logged-in',
                '.woocommerce-MyAccount-navigation',
            ]

            for selector in auth_indicators:
                try:
                    if await self.page.locator(selector).count() > 0:
                        logger.info(f"[{self.SITE_NAME}] Найден признак авторизации: {selector}")
                        return True
                except:
                    continue

            # Если видим форму входа - не авторизованы
            if await self.page.locator('input[type="password"]').count() > 0:
                return False

            # Проверяем наличие кнопки "Войти" на странице
            if await self.page.locator('a:has-text("Войти")').count() > 0:
                return False

            return False

        except Exception as e:
            logger.error(f"[{self.SITE_NAME}] Ошибка проверки авторизации: {e}")
            return False

    async def auto_login(self) -> bool:
        """Выполнить автоматический логин на auto-vid.com.

        ВАЖНО: Перед входом нужно поставить галочку согласия с политикой конфиденциальности!
        """
        try:
            logger.info(f"[{self.SITE_NAME}] Начинаю автологин...")

            # Переходим на страницу входа для оптовых покупателей
            await self.page.goto(self.LOGIN_URL, wait_until='networkidle', timeout=60000)
            await self.page.wait_for_timeout(2000)

            # Ищем поле email/логина
            login_selectors = [
                'input[name="username"]',
                'input[name="email"]',
                'input[name="login"]',
                'input[type="email"]',
                'input[id="username"]',
                'input[id="email"]',
                '#user_login',
                'input[placeholder*="почт" i]',
                'input[placeholder*="email" i]',
                'input[placeholder*="логин" i]',
            ]

            login_field = None
            for selector in login_selectors:
                if await self.page.locator(selector).count() > 0:
                    login_field = selector
                    break

            if login_field:
                await self.page.fill(login_field, AUTOVID_LOGIN)
                logger.info(f"[{self.SITE_NAME}] Email введён: {AUTOVID_LOGIN}")
            else:
                logger.error(f"[{self.SITE_NAME}] Поле логина не найдено")
                # Debug
                try:
                    inputs = await self.page.locator('input').all()
                    logger.error(f"[{self.SITE_NAME}] Найдено {len(inputs)} input элементов")
                    for inp in inputs[:10]:
                        attrs = await inp.evaluate('el => ({name: el.name, type: el.type, id: el.id, placeholder: el.placeholder})')
                        logger.error(f"  input: {attrs}")
                except:
                    pass
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
                await self.page.fill(password_field, AUTOVID_PASSWORD)
                logger.info(f"[{self.SITE_NAME}] Пароль введён")
            else:
                logger.error(f"[{self.SITE_NAME}] Поле пароля не найдено")
                return False

            # ВАЖНО: Ставим галочку согласия с политикой конфиденциальности
            # Это обязательное условие перед входом!
            privacy_checkbox_selectors = [
                'input[name="privacy_policy"]',
                'input[name="privacy"]',
                'input[name="agree"]',
                'input[name="terms"]',
                'input[type="checkbox"][name*="privacy" i]',
                'input[type="checkbox"][name*="policy" i]',
                'input[type="checkbox"][name*="agree" i]',
                'input[type="checkbox"][id*="privacy" i]',
                'input[type="checkbox"][id*="policy" i]',
                # WooCommerce checkboxes
                '.woocommerce-form__input-checkbox',
                'input.woocommerce-form__input-checkbox',
                # Generic checkbox near login button
                'form input[type="checkbox"]',
            ]

            checkbox_clicked = False
            for selector in privacy_checkbox_selectors:
                try:
                    checkbox = self.page.locator(selector).first
                    if await checkbox.is_visible(timeout=2000):
                        # Проверяем, не отмечен ли уже
                        is_checked = await checkbox.is_checked()
                        if not is_checked:
                            await checkbox.click()
                            logger.info(f"[{self.SITE_NAME}] Галочка согласия поставлена: {selector}")
                        else:
                            logger.info(f"[{self.SITE_NAME}] Галочка уже стоит: {selector}")
                        checkbox_clicked = True
                        break
                except:
                    continue

            if not checkbox_clicked:
                # Пробуем найти любой чекбокс на форме
                try:
                    all_checkboxes = await self.page.locator('input[type="checkbox"]').all()
                    logger.info(f"[{self.SITE_NAME}] Найдено {len(all_checkboxes)} чекбоксов")
                    for cb in all_checkboxes:
                        try:
                            if await cb.is_visible():
                                is_checked = await cb.is_checked()
                                if not is_checked:
                                    await cb.click()
                                    logger.info(f"[{self.SITE_NAME}] Кликнули на видимый чекбокс")
                                    checkbox_clicked = True
                                    break
                        except:
                            continue
                except Exception as e:
                    logger.warning(f"[{self.SITE_NAME}] Ошибка поиска чекбокса: {e}")

            if not checkbox_clicked:
                logger.warning(f"[{self.SITE_NAME}] Галочка согласия не найдена, пробуем войти без неё")

            await self.page.wait_for_timeout(500)

            # Нажимаем кнопку входа
            submit_selectors = [
                'button[name="login"]',
                'button[type="submit"]:has-text("Войти")',
                'input[type="submit"][value*="Войти" i]',
                'button:has-text("Войти")',
                'input[value="Войти"]',
                '.woocommerce-form-login__submit',
                'button.woocommerce-button',
                'form button[type="submit"]',
            ]

            submit_clicked = False
            for selector in submit_selectors:
                try:
                    btn = self.page.locator(selector).first
                    if await btn.is_visible(timeout=2000):
                        await btn.click()
                        logger.info(f"[{self.SITE_NAME}] Нажата кнопка входа: {selector}")
                        submit_clicked = True
                        break
                except:
                    continue

            if not submit_clicked:
                # Попробуем нажать Enter
                logger.warning(f"[{self.SITE_NAME}] Кнопка входа не найдена, нажимаем Enter")
                await self.page.locator('input[type="password"]').press("Enter")

            # Ждём загрузки
            await self.page.wait_for_timeout(5000)

            logger.info(f"[{self.SITE_NAME}] URL после логина: {self.page.url}")

            # Проверяем успешность
            if await self.check_auth():
                logger.info(f"[{self.SITE_NAME}] Авторизация успешна!")
                await self._save_cookies_to_backup()
                return True
            else:
                logger.error(f"[{self.SITE_NAME}] Авторизация не удалась")
                # Проверяем, есть ли сообщение об ошибке
                try:
                    error_msg = await self.page.locator('.woocommerce-error, .error, .alert-danger').inner_text()
                    logger.error(f"[{self.SITE_NAME}] Сообщение об ошибке: {error_msg}")
                except:
                    pass
                return False

        except Exception as e:
            logger.error(f"[{self.SITE_NAME}] Ошибка автологина: {e}")
            return False

    async def keep_alive(self) -> None:
        """Keep-alive для auto-vid.com."""
        try:
            logger.debug(f"[{self.SITE_NAME}] Keep-alive: проверка сессии...")

            await self.page.evaluate('''
                fetch("/", {method: "HEAD", credentials: "include"})
                    .catch(() => {});
            ''')

            logger.debug(f"[{self.SITE_NAME}] Keep-alive OK")

        except Exception as e:
            logger.warning(f"[{self.SITE_NAME}] Keep-alive ошибка: {e}")

    # ========== Методы поиска ==========

    async def search_part(self, partnumber: str, brand_filter: str = None) -> Dict[str, Any]:
        """Поиск запчасти по артикулу.

        Args:
            partnumber: Артикул для поиска
            brand_filter: Фильтр по бренду (необязательно)
        """
        try:
            # Сначала переходим на главную страницу
            await self.page.goto(self.BASE_URL, wait_until='load', timeout=60000)
            await self.page.wait_for_timeout(3000)

            # Проверяем авторизацию
            if not await self.check_auth():
                logger.warning(f"[{self.SITE_NAME}] Сессия истекла, повторный вход...")
                await self.auto_login()

            # Ищем поле поиска на странице с различными селекторами
            search_selectors = [
                'input[type="search"]',
                'input[name="s"]',
                '.search-field',
                '#s',
                'input.dgwt-wcas-search-input',  # WooCommerce AJAX search
                '.woocommerce-product-search input',
                'form.search-form input[type="text"]',
                'header input[type="text"]',
            ]

            search_input = None
            for sel in search_selectors:
                try:
                    loc = self.page.locator(sel).first
                    if await loc.is_visible(timeout=1000):
                        search_input = loc
                        logger.info(f"[{self.SITE_NAME}] Найдено поле поиска: {sel}")
                        break
                except:
                    continue

            if search_input:
                await search_input.fill(partnumber)
                await self.page.keyboard.press('Enter')
                await self.page.wait_for_load_state('networkidle', timeout=30000)
                await self.page.wait_for_timeout(5000)  # Дополнительное ожидание для AJAX
            else:
                # Fallback: прямой URL
                search_url = f"{self.BASE_URL}/?s={partnumber}&post_type=product"
                logger.info(f"[{self.SITE_NAME}] Поле поиска не найдено, используем URL: {search_url}")
                await self.page.goto(search_url, wait_until='load', timeout=60000)
                await self.page.wait_for_timeout(8000)  # Больше времени для JS

            logger.info(f"[{self.SITE_NAME}] Поиск: {partnumber}")

            # Если указан brand_filter, фильтруем результаты
            if brand_filter:
                logger.info(f"[{self.SITE_NAME}] Фильтр по бренду: {brand_filter}")

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
            logger.error(f"[{self.SITE_NAME}] Ошибка поиска: {e}")
            return {
                'partnumber': partnumber,
                'status': 'error',
                'prices': {'min': None, 'avg': None},
                'error': str(e)
            }

    async def search_part_with_retry(self, partnumber: str, brand_filter: str = None, max_retries: int = 3) -> Dict[str, Any]:
        """Поиск с повторными попытками."""
        for attempt in range(1, max_retries + 1):
            logger.info(f"[{self.SITE_NAME}] Попытка {attempt}/{max_retries}: {partnumber}" + (f" [бренд: {brand_filter}]" if brand_filter else ""))

            result = await self.search_part(partnumber, brand_filter=brand_filter)

            if result.get('status') == 'success' and result.get('prices', {}).get('min'):
                return result

            if attempt < max_retries:
                await asyncio.sleep(2 * attempt)

        return result

    async def _extract_prices_and_brand(self, brand_filter: str = None) -> Dict[str, Any]:
        """Извлечь цены и бренд из результатов поиска WooCommerce."""
        prices = []
        brand = None
        total_count = 0
        filtered_count = 0

        try:
            await self.page.wait_for_timeout(2000)

            # Проверяем наличие результатов
            page_text = await self.page.inner_text('body')
            if 'ничего не найдено' in page_text.lower() or 'no products' in page_text.lower():
                logger.info(f"[{self.SITE_NAME}] Товары не найдены")
                return {'prices': [], 'brand': None}

            # WooCommerce структура - различные селекторы для товаров
            product_selectors = [
                'ul.products li.product',
                '.products .product',
                'li.product',
                '.product-item',
                'article.product',
            ]

            products = []
            for selector in product_selectors:
                products = await self.page.locator(selector).all()
                if len(products) > 0:
                    logger.info(f"[{self.SITE_NAME}] Найдено {len(products)} товаров ({selector})")
                    break

            if len(products) == 0:
                logger.warning(f"[{self.SITE_NAME}] Товары не найдены стандартными селекторами")

                # Попробуем найти товарные блоки по OpenCart структуре (product-layout)
                products = await self.page.locator('.product-layout, .product-thumb').all()
                logger.info(f"[{self.SITE_NAME}] Найдено {len(products)} товаров (OpenCart)")

            # Обрабатываем найденные товары
            for product in products:
                try:
                    product_text = await product.inner_text()
                    total_count += 1

                    # ФИЛЬТР: Проверяем наличие на складе
                    # Пропускаем товары "Нет в наличии"
                    out_of_stock_markers = ['нет в наличии', 'нет на складе', 'out of stock', 'недоступен']
                    is_out_of_stock = any(marker in product_text.lower() for marker in out_of_stock_markers)
                    if is_out_of_stock:
                        logger.debug(f"[{self.SITE_NAME}] Товар пропущен (нет в наличии)")
                        continue

                    # ФИЛЬТР: Проверяем бренд
                    if brand_filter:
                        if brand_filter.lower() not in product_text.lower():
                            logger.debug(f"[{self.SITE_NAME}] Товар пропущен (бренд не совпадает): {product_text[:50]}...")
                            continue

                    filtered_count += 1

                    # Сохраняем бренд
                    if not brand and brand_filter:
                        brand = brand_filter

                    # Извлекаем цену
                    price_el = product.locator('.price, .price-new, [class*="price"]').first
                    if await price_el.count() > 0:
                        price_text = await price_el.inner_text()

                        # Берём все цены и выбираем минимальную (актуальную)
                        price_matches = re.findall(r'([\d\s\xa0,.]+)\s*[₽руб]', price_text)
                        for price_str in price_matches:
                            try:
                                price_clean = price_str.replace(" ", "").replace("\xa0", "").replace(",", ".").strip()
                                if price_clean:
                                    val = float(price_clean)
                                    # Снизили минимум до 10₽ для дешёвых товаров
                                    if 10 < val < 500000:
                                        prices.append(val)
                                        logger.debug(f"[{self.SITE_NAME}] Найдена цена: {val}₽")
                            except ValueError:
                                continue
                    else:
                        # Fallback: ищем цену в тексте товара
                        price_matches = re.findall(r'([\d\s\xa0,.]+)\s*[₽руб]', product_text)
                        for price_str in price_matches:
                            try:
                                price_clean = price_str.replace(" ", "").replace("\xa0", "").replace(",", ".").strip()
                                if price_clean:
                                    val = float(price_clean)
                                    if 10 < val < 500000:
                                        prices.append(val)
                            except ValueError:
                                continue

                except Exception as e:
                    logger.debug(f"[{self.SITE_NAME}] Ошибка парсинга товара: {e}")
                    continue

        except Exception as e:
            logger.error(f"[{self.SITE_NAME}] Ошибка извлечения данных: {e}")

        if total_count > 0:
            logger.info(f"[{self.SITE_NAME}] Обработано товаров: {filtered_count}/{total_count} (в наличии + бренд '{brand_filter or 'любой'}')")

        unique_prices = list(set(prices))
        if unique_prices:
            logger.info(f"[{self.SITE_NAME}] Найдено {len(unique_prices)} уникальных цен: {sorted(unique_prices)[:5]}...")
        else:
            logger.warning(f"[{self.SITE_NAME}] Цены не найдены")

        return {'prices': unique_prices, 'brand': brand}


# ========== Тест ==========

async def test_client():
    """Тест CDP клиента."""
    logging.basicConfig(level=logging.INFO)

    async with AutoVidCDPClient() as client:
        print(f"Подключено: {client.is_connected}")
        print(f"Авторизован: {client.is_logged_in}")
        print(f"URL: {client.url}")

        # Тестовый поиск
        result = await client.search_part("7PK3170")
        print(f"Результат: {result}")


if __name__ == "__main__":
    asyncio.run(test_client())
