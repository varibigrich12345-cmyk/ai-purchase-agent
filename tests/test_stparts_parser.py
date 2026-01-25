"""Unit-тесты для парсера STparts."""
import pytest
import re


def extract_price(text: str) -> float | None:
    """Извлечь цену из текста STparts."""
    match = re.search(r"([\d\s]+[,.]?\d*)\s*₽", text)
    if match:
        try:
            price_str = match.group(1).replace(" ", "").replace("\xa0", "").replace(",", ".")
            val = float(price_str)
            if 10 < val < 500000:
                return val
        except ValueError:
            pass
    return None


class TestExtractPrice:
    def test_simple(self):
        assert extract_price("141,40 ₽") == 141.40
    
    def test_thousands(self):
        assert extract_price("1 234,56 ₽") == 1234.56
    
    def test_no_decimal(self):
        assert extract_price("500 ₽") == 500.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

