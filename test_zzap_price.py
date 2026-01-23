"""Тест парсера ZZAP для артикула 1751493 FORD."""

import asyncio
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from zzap_cdp_client import ZZapCDPClient

async def test():
    async with ZZapCDPClient() as client:
        print("=" * 60)
        print("Тест: 1751493 FORD")
        print("Ожидаемая минимальная цена: 5800₽ (ЗапМотор)")
        print("=" * 60)

        result = await client.search_part("1751493", brand_filter="FORD")

        print("\nРезультат:")
        print(f"  Статус: {result.get('status')}")
        print(f"  Бренд: {result.get('brand')}")
        if result.get('prices'):
            print(f"  Мин. цена: {result['prices']['min']}₽")
            print(f"  Средняя: {result['prices']['avg']}₽")
        print(f"  URL: {result.get('url')}")

if __name__ == "__main__":
    asyncio.run(test())
