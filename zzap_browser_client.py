"""
Playwright клиент для парсинга zzap.ru
ФИНАЛЬНАЯ РАБОЧАЯ ВЕРСИЯ
"""
import asyncio
import re
import logging
from typing import Optional, Dict, List
from playwright.async_api import async_playwright, Page, Browser, TimeoutError as PlaywrightTimeout


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ZZapBrowserClient:
    def __init__(self, headless: bool = True):
        self.browser: Optional[Browser] = None
        self.context = None
        self.page: Optional[Page] = None
        self.playwright = None
        self.headless = headless

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def start(self):
        """Запустить браузер"""
        try:
            logger.info("🚀 Запуск браузера...")
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=self.headless,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox'
                ]
            )
            self.context = await self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            self.page = await self.context.new_page()
            logger.info(f"✅ Браузер запущен (headless={self.headless})")
        except Exception as e:
            logger.error(f"❌ Ошибка запуска: {e}")
            raise

    async def close(self):
        """Закрыть браузер"""
        try:
            if self.page:
                await self.page.close()
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            logger.info("✅ Браузер закрыт")
        except Exception as e:
            logger.error(f"❌ Ошибка закрытия: {e}")

    async def search_part_with_retry(self, partnumber: str, max_retries: int = 3) -> Dict:
        """Поиск с retry"""
        for attempt in range(max_retries):
            try:
                logger.info(f"🔍 Попытка {attempt + 1}/{max_retries}: {partnumber}")
                if attempt > 0:
                    import random
                    delay = (2 ** attempt) + random.uniform(0, 1)
                    logger.info(f"⏳ Ожидание {delay:.1f}с...")
                    await asyncio.sleep(delay)

                result = await self.search_part(partnumber)
                if result.get('prices'):
                    logger.info(f"✅ Успех! min={result['prices']['min']}, avg={result['prices']['avg']}")
                    return result
                else:
                    logger.warning(f"⚠️ Нет цен, попытка {attempt + 1}")
            except Exception as e:
                logger.error(f"❌ Ошибка попытки {attempt + 1}: {e}")
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

    async def search_part(self, partnumber: str) -> Dict:
        """Выполнить поиск"""
        try:
            # 1. Переход на страницу
            url = f"https://www.zzap.ru/public/search.aspx?rawdata={partnumber}"
            logger.info(f"📡 Переход: {url}")
            await self.page.goto(url, wait_until='domcontentloaded', timeout=30000)
            await asyncio.sleep(3)

            # 2. Проверка и обработка модального окна
            modal_popup = self.page.locator('#ctl00_TopPanel_HeaderPlace_GridLayoutSearchControl_SearchSuggestPopupControl_PWC-1')
            
            try:
                # Ждем появления модального окна (или его отсутствия)
                await modal_popup.wait_for(state='visible', timeout=5000)
                logger.info("🔔 Модальное окно обнаружено - выбираем первый вариант")
                
                # ВАЖНО: Используем правильный ID таблицы модального окна
                first_row = self.page.locator('#ctl00_TopPanel_HeaderPlace_GridLayoutSearchControl_SearchSuggestPopupControl_SearchSuggestGridView_DXDataRow0')
                
                if await first_row.count() > 0:
                    logger.info("✅ Кликаем на первую строку...")
                    await first_row.click(timeout=5000)
                    logger.info("✅ Клик выполнен!")
                    
                    # КРИТИЧЕСКИ ВАЖНО: Ждем, пока модальное окно исчезнет
                    await modal_popup.wait_for(state='hidden', timeout=5000)
                    logger.info("✅ Модальное окно закрылось")
                    
                else:
                    logger.warning("⚠️ Строка не найдена в модальном окне")
                    
            except PlaywrightTimeout:
                logger.info("ℹ️ Модальное окно не появилось (возможно, один результат)")

            # 3. Ждем появления таблицы результатов
            logger.info("⏳ Ожидание загрузки таблицы результатов...")
            try:
                await self.page.wait_for_selector('#ctl00_BodyPlace_SearchGridView_DXMainTable', timeout=15000)
                logger.info("✅ Таблица найдена!")
            except PlaywrightTimeout:
                logger.error("❌ Таблица не появилась")
                return {'partnumber': partnumber, 'status': 'NO_RESULTS', 'prices': None, 'url': self.page.url}

            # 4. КРИТИЧЕСКИ ВАЖНО: Ждем загрузки данных через AJAX
            # Проверяем, что в таблице НЕТ сообщения "Нет никаких данных"
            logger.info("⏳ Ожидание загрузки данных (AJAX)...")
            for i in range(15):  # Максимум 15 секунд ожидания
                page_text = await self.page.inner_text('body')
                if 'Нет никаких данных' not in page_text and 'Одна минута' not in page_text:
                    logger.info(f"✅ Данные загрузились за {i+1} сек!")
                    break
                await asyncio.sleep(1)
            else:
                logger.warning("⚠️ Данные не загрузились за 15 секунд")

            # Дополнительная пауза для стабильности
            await asyncio.sleep(2)

            # 5. Парсинг цен
            prices = await self._extract_prices()
            
            if not prices:
                logger.warning("⚠️ Цены не найдены")
                return {'partnumber': partnumber, 'status': 'NO_RESULTS', 'prices': None, 'url': self.page.url}

            return {
                'partnumber': partnumber,
                'status': 'DONE',
                'prices': {
                    'min': min(prices),
                    'avg': round(sum(prices) / len(prices), 2)
                },
                'url': self.page.url
            }
            
        except Exception as e:
            logger.error(f"❌ Ошибка поиска: {e}")
            raise

    async def _extract_prices(self) -> List[float]:
        """
        Извлекает цены из таблицы результатов.
        Парсит только ячейки "Цена и условия", игнорируя фильтры и служебную информацию.
        """
        prices = []
        try:
            # Основная таблица результатов
            table = self.page.locator("table#ctl00_BodyPlace_SearchGridView_DXMainTable")
            
            # Проверяем, что таблица видна
            if not await table.is_visible(timeout=5000):
                logger.warning("⚠️ [ZZAP] Таблица результатов не видна")
                return prices
            
            # Получаем все строки данных
            rows = await table.locator("tr").all()
            logger.info(f"📋 [ZZAP] Найдено строк в таблице: {len(rows)}")
            
            for row in rows:
                try:
                    # Ищем ячейки с ценами
                    cells = await row.locator("td").all()
                    
                    for cell in cells:
                        cell_text = await cell.inner_text()
                        
                        # Пропускаем служебные строки
                        if "Свернуть" in cell_text or "Запрошенный номер" in cell_text:
                            break
                        
                        # Ищем паттерн цены: число + "р."
                        # Но ТОЛЬКО если это не "Заказ от" или фильтр
                        if "р." in cell_text and "Заказ от" not in cell_text:
                            match = re.search(r"^(\d[\d\s]*)\s*р\.", cell_text.strip())
                            if match:
                                price_str = match.group(1).replace(" ", "").replace("\xa0", "")
                                try:
                                    price = float(price_str)
                                    # Фильтруем явно неправильные значения
                                    if 1500 < price < 100000:
                                        prices.append(price)
                                        logger.debug(f"💰 [ZZAP] Цена: {price}")
                                except ValueError:
                                    continue
                except Exception as e:
                    logger.debug(f"Ошибка обработки строки: {e}")
                    continue
            
            # Убираем дубликаты
            prices = list(set(prices))
            
            if prices:
                logger.info(f"✅ [ZZAP] Найдено {len(prices)} уникальных цен: {sorted(prices)[:10]}...")
            else:
                logger.warning("⚠️ [ZZAP] Цены не найдены!")
            
        except Exception as e:
            logger.error(f"❌ [ZZAP] Ошибка извлечения цен: {e}")
        
        return prices
