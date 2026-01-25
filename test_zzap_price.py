"""
Локальный тест парсера ZZAP - проверяет фильтрацию б/у и выбор минимальной цены
Запуск: python test_zzap_price.py
"""

import asyncio
from playwright.async_api import async_playwright

ZZAP_URL = "https://www.zzap.ru/public/search.aspx#rawdata=1751493&class_man=FORD&partnumber=1751493"

async def test_zzap_parsing():
    print("=" * 60)
    print("ТЕСТ ПАРСЕРА ZZAP - артикул 1751493, бренд FORD")
    print("=" * 60)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # headless=False чтобы видеть
        page = await browser.new_page()
        
        print("\n1. Переход на страницу...")
        await page.goto(ZZAP_URL, wait_until='networkidle', timeout=60000)
        await page.wait_for_timeout(3000)
        
        print("\n2. Поиск всех строк таблицы (DXDataRow)...")
        rows = await page.locator("tr[id*='DXDataRow']").all()
        print(f"   Найдено строк: {len(rows)}")
        
        prices_found = []
        
        print("\n3. Анализ каждой строки:")
        print("-" * 60)
        
        for i, row in enumerate(rows[:10]):  # Первые 10 строк
            row_id = await row.get_attribute('id')
            row_text = await row.text_content()
            row_text_clean = ' '.join(row_text.split())[:200]
            
            # Проверка на б/у
            is_bu = any(x in row_text.lower() for x in ['б/у', 'б у', 'уценка', 'бывш'])
            
            # НОВЫЙ ПОДХОД: парсим по ЯЧЕЙКАМ таблицы
            # Цена находится в ячейке "Цена и условия" (обычно 6-7 ячейка)
            # В этой ячейке ищем ПЕРВОЕ число с "р." - это цена товара
            import re
            
            # Получаем все ячейки строки
            cells = await row.locator('td').all()
            print(f"\n   Строка {i+1} [{row_id}]:")
            print(f"   Ячеек в строке: {len(cells)}")
            
            # Для строки DXDataRow4 выводим ВСЕ ячейки
            if 'DXDataRow4' in (row_id or ''):
                print(f"\n   📋 ВСЕ ЯЧЕЙКИ для {row_id}:")
                for idx, cell in enumerate(cells):
                    try:
                        cell_text = await cell.inner_text()
                        print(f"   Ячейка {idx}: {cell_text[:100]}")
                    except Exception as e:
                        print(f"   Ячейка {idx}: [ошибка чтения: {e}]")
                print()
            
            price = None
            price_cell_index = None
            price_cell_text = None
            
            # Ищем ячейку с ценой (содержит "р.")
            for idx, cell in enumerate(cells):
                try:
                    cell_text = await cell.inner_text()
                    if "р." in cell_text:
                        # ПРАВИЛЬНАЯ ЛОГИКА: удаляем паттерн "Заказ от X р." из текста
                        # Затем ищем оставшиеся цены - это реальные цены товара
                        cell_text_clean = cell_text
                        
                        # Удаляем паттерн "Заказ от [число] р." (регистронезависимо)
                        # Паттерн: "Заказ от" + пробелы + число + пробелы + "р."
                        cell_text_clean = re.sub(
                            r'заказ\s+от\s+[\d\s\xa0]+\s*р\.',
                            '',
                            cell_text_clean,
                            flags=re.IGNORECASE
                        )
                        
                        # Если удалили "Заказ от", логируем
                        if cell_text_clean != cell_text:
                            print(f"   📍 Найдено 'Заказ от' в ячейке {idx}, удаляем паттерн")
                            print(f"   Оригинальный текст: {cell_text[:100]}")
                            print(f"   Очищенный текст: {cell_text_clean[:100]}")
                        
                        # Ищем цены в очищенном тексте (это реальные цены товара)
                        for match in re.finditer(r'(\d[\d\s\xa0]*)\s*р\.', cell_text_clean):
                            price_str = match.group(1).replace(' ', '').replace('\xa0', '').replace('\n', '')
                            try:
                                candidate_price = float(price_str)
                                if 50 < candidate_price < 500000:  # Разумный диапазон цен
                                    # Это реальная цена товара (не из "Заказ от")
                                    price = candidate_price
                                    price_cell_index = idx
                                    price_cell_text = cell_text.strip()
                                    print(f"   ✅ Найдена цена {price}р в ячейке {idx} (после удаления 'Заказ от'): {cell_text_clean[:100]}")
                                    break  # Берем первую найденную цену
                            except ValueError:
                                continue
                        
                        # Если нашли цену в этой ячейке, выходим из цикла по ячейкам
                        if price:
                            break
                except Exception as e:
                    print(f"   ⚠️ Ошибка при обработке ячейки {idx}: {e}")
                    continue
            
            status = "❌ Б/У - ПРОПУСТИТЬ" if is_bu else "✅ НОВЫЙ"
            
            print(f"   Текст строки: {row_text_clean}...")
            if price:
                print(f"   Выбранная цена: {price}р (ячейка {price_cell_index})")
                print(f"   Текст ячейки с ценой: {price_cell_text[:150]}")
            else:
                print(f"   Цена: не найдена в ячейках")
            print(f"   Статус: {status}")
            
            if price and not is_bu:
                prices_found.append(price)
        
        print("\n" + "=" * 60)
        print("РЕЗУЛЬТАТ:")
        print(f"   Все новые цены: {sorted(prices_found)}")
        print(f"   Минимальная цена: {min(prices_found) if prices_found else 'НЕТ'}")
        print(f"   Ожидаемая: 5800р")
        print("=" * 60)
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(test_zzap_parsing())
