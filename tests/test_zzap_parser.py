"""
Unit-тесты для парсера ZZAP.
Тестируют логику извлечения цен без реального браузера.
"""

import pytest
import re


def extract_price_from_cell(cell_text: str) -> float | None:
    """Извлечь цену из текста ячейки."""
    cleaned_text = re.sub(r'Заказ от\s*[\d\s]+р\.?', '', cell_text, flags=re.IGNORECASE)
    
    for match in re.finditer(r'(\d[\d\s\xa0]*)\s*р\.', cleaned_text):
        price_str = match.group(1).replace(" ", "").replace("\xa0", "").replace("\n", "")
        try:
            price = float(price_str)
            if 50 < price < 500000:
                return price
        except ValueError:
            continue
    return None


def is_used_product(row_text: str) -> bool:
    """Проверить, является ли товар б/у."""
    row_text_lower = row_text.lower()
    return any(x in row_text_lower for x in ["б/у", "б у", "уценка", "бывш", "в употреблении"])


class TestExtractPrice:
    def test_simple_price(self):
        assert extract_price_from_cell("6 400р.") == 6400.0
    
    def test_price_with_zakaz_ot(self):
        cell_text = "Заказ от 10 000р.\n\n5 800р.\nНаличный расчет."
        assert extract_price_from_cell(cell_text) == 5800.0
    
    def test_price_with_zakaz_ot_small(self):
        cell_text = "Заказ от 1 000р.\n\n7 360р."
        assert extract_price_from_cell(cell_text) == 7360.0


class TestIsUsedProduct:
    def test_bu(self):
        assert is_used_product("б/у и уценка Насос") is True
    
    def test_new(self):
        assert is_used_product("Насос вакуумный TRANSIT") is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

