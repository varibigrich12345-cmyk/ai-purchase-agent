"""
Unit-тесты для парсера Trast.
"""

import pytest
import re


# Маппинг брендов из trast_cdp_client.py
BRAND_MAPPING = {
    'peugeot': ['peugeot-citroen', 'peugeot', 'citroen', 'psa'],
    'citroen': ['peugeot-citroen', 'citroen', 'peugeot', 'psa'],
    'ford': ['ford'],
    'toyota': ['toyota'],
    'renault': ['renault'],
    'hyundai': ['hyundai', 'kia', 'mobis'],
    'kia': ['kia', 'hyundai', 'mobis'],
}


def matches_brand_filter(manufacturer: str, brand_filter: str) -> bool:
    """Проверить соответствие производителя фильтру."""
    if not brand_filter or not manufacturer:
        return True
    
    brand_lower = brand_filter.lower().strip()
    manuf_lower = manufacturer.lower().strip()
    
    allowed = BRAND_MAPPING.get(brand_lower, [brand_lower])
    return any(a in manuf_lower for a in allowed)


def extract_price(text: str) -> float | None:
    """Извлечь цену из текста."""
    match = re.search(r'([\d\s\xa0]{1,15})\s*₽', text)
    if match:
        price_str = match.group(1).replace(" ", "").replace("\xa0", "")
        try:
            val = float(price_str)
            if 100 < val < 500000:
                return val
        except ValueError:
            pass
    return None


class TestBrandMapping:
    def test_peugeot_citroen(self):
        assert matches_brand_filter("PEUGEOT-CITROEN", "peugeot") is True
        assert matches_brand_filter("PEUGEOT-CITROEN", "citroen") is True
    
    def test_exact_match(self):
        assert matches_brand_filter("FORD", "ford") is True
        assert matches_brand_filter("TOYOTA", "toyota") is True
    
    def test_no_match(self):
        assert matches_brand_filter("BMW", "ford") is False
    
    def test_hyundai_kia(self):
        assert matches_brand_filter("HYUNDAI/KIA", "hyundai") is True
        assert matches_brand_filter("MOBIS", "kia") is True


class TestExtractPrice:
    def test_simple(self):
        assert extract_price("4 700₽") == 4700.0
    
    def test_nbsp(self):
        assert extract_price("10\xa0800₽") == 10800.0
    
    def test_no_price(self):
        assert extract_price("В наличии") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

