"""Unit-тесты для парсера AutoVID."""
import pytest
import re


def extract_price(text: str) -> float | None:
    """Извлечь цену из текста AutoVID."""
    matches = re.findall(r'([\d\s\xa0,.]+)\s*[₽руб]', text)
    for price_str in matches:
        try:
            price_clean = price_str.replace(" ", "").replace("\xa0", "").replace(",", ".")
            if price_clean:
                val = float(price_clean)
                if 10 < val < 500000:
                    return val
        except ValueError:
            continue
    return None


def is_out_of_stock(text: str) -> bool:
    """Проверить, нет ли товара в наличии."""
    markers = ['нет в наличии', 'нет на складе', 'out of stock', 'недоступен']
    return any(m in text.lower() for m in markers)


class TestExtractPrice:
    def test_rub(self):
        assert extract_price("4 500 руб") == 4500.0
    
    def test_symbol(self):
        assert extract_price("3 200₽") == 3200.0


class TestOutOfStock:
    def test_out(self):
        assert is_out_of_stock("Товар нет в наличии") is True
    
    def test_available(self):
        assert is_out_of_stock("В наличии 5 шт") is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

