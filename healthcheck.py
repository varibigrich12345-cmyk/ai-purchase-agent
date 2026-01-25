"""
Healthcheck для мониторинга парсеров.
Запуск: python healthcheck.py
"""

import asyncio
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Тестовые артикулы для проверки
TEST_ARTICLES = {
    'zzap': ('1751493', 'FORD'),
    'trast': ('1920QK', 'PEUGEOT'),
}

async def check_zzap():
    """Проверка ZZAP парсера."""
    try:
        from zzap_cdp_client import ZZapCDPClient
        async with ZZapCDPClient() as client:
            result = await client.search_part('1751493', 'FORD')
            if result.get('prices') and result['prices'].get('min'):
                return True, f"OK: {result['prices']['min']}₽"
            return False, "NO_RESULTS"
    except Exception as e:
        return False, str(e)

async def check_trast():
    """Проверка Trast парсера."""
    try:
        from trast_cdp_client import TrastCDPClient
        async with TrastCDPClient() as client:
            result = await client.search_part('1920QK', 'PEUGEOT')
            if result.get('prices') and result['prices'].get('min'):
                return True, f"OK: {result['prices']['min']}₽"
            return False, "NO_RESULTS"
    except Exception as e:
        return False, str(e)

async def run_healthcheck():
    """Запуск всех проверок."""
    print(f"\n{'='*50}")
    print(f"Healthcheck: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}\n")
    
    checks = [
        ('ZZAP', check_zzap),
        ('Trast', check_trast),
    ]
    
    results = []
    for name, check_func in checks:
        ok, msg = await check_func()
        status = "✅" if ok else "❌"
        print(f"{status} {name}: {msg}")
        results.append((name, ok, msg))
    
    print(f"\n{'='*50}")
    
    failed = [r for r in results if not r[1]]
    if failed:
        print(f"⚠️ FAILED: {len(failed)} парсеров не работают!")
        return False
    else:
        print("✅ Все парсеры работают!")
        return True

if __name__ == "__main__":
    asyncio.run(run_healthcheck())

