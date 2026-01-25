"""Unit-тесты для парсера AutoTrade."""
import pytest
import re


def extract_price_from_row(row_text: str) -> float | None:
    """Извлечь цену ТОЛЬКО из строки с артикулом (не из баланса!)."""
    if 'Артикул:' not in row_text:
        return None  # Игнорируем строки без артикула
    
    match = re.search(r'(\d[\d\s,\.]*)\s*RUB', row_text)
    if match:
        try:
            price_str = match.group(1).replace(" ", "").replace("\xa0", "").replace(",", ".")
            val = float(price_str)
            if 10 < val < 500000:
                return val
        except ValueError:
            pass
    return None


def check_no_results(page_text: str) -> bool:
    """Проверить отсутствие результатов."""
    indicators = ['ничего не найдено', 'нет результатов', 'no results']
    return any(i in page_text.lower() for i in indicators)


class TestExtractPrice:
    def test_with_article(self):
        row = "Артикул: ST-123, Бренд: SAT | 935 RUB"
        assert extract_price_from_row(row) == 935.0
    
    def test_without_article(self):
        # Баланс счёта - НЕ должен парситься как цена!
        row = "Баланс: 92 585 RUB"
        assert extract_price_from_row(row) is None
    
    def test_price_with_spaces(self):
        row = "Артикул: ABC-1, Бренд: XYZ | 1 234 RUB"
        assert extract_price_from_row(row) == 1234.0


class TestNoResults:
    def test_nothing_found(self):
        assert check_no_results("По вашему запросу ничего не найдено") is True
    
    def test_has_results(self):
        assert check_no_results("Артикул: ST-123") is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

