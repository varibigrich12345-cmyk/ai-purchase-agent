"""
Тестовый скрипт для проверки stparts_browser_client.py
"""

import asyncio
import logging
from playwright.async_api import async_playwright
from stparts_browser_client import STPartsBrowserClient

# Включаем логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_stparts():
    """
    Простой тест для проверки работы клиента.
    """
    print("🧪 Запуск теста STparts клиента...")
    
    # Запускаем Playwright
    async with async_playwright() as pw:
        # Создаём клиент (headless=False чтобы видеть браузер)
        client = STPartsBrowserClient(pw, headless=False)
        
        # Открываем браузер и логинимся
        async with client:
            print("✅ Браузер запущен и авторизован")
            
            # Пробуем найти запчасть
            partnumber = "1351PK"  # Замени на реальный артикул
            print(f"\n🔍 Ищем артикул: {partnumber}")
            
            result = await client.search_part_with_retry(partnumber, max_retries=2)
            
            # Выводим результат
            print("\n📊 Результат:")
            print(f"  Статус: {result['status']}")
            print(f"  Артикул: {result['partnumber']}")
            
            if result.get('prices'):
                print(f"  Мин. цена: {result['prices']['min']} ₽")
                print(f"  Средняя: {result['prices']['avg']} ₽")
            
            if result.get('url'):
                print(f"  URL: {result['url']}")
            
            if result.get('error'):
                print(f"  Ошибка: {result['error']}")
            
            # Ждём 5 секунд чтобы посмотреть на результат
            print("\n⏳ Ждём 5 секунд перед закрытием...")
            await asyncio.sleep(5)
    
    print("\n✅ Тест завершён!")

if __name__ == "__main__":
    # Запускаем тест
    asyncio.run(test_stparts())