# test_stparts.py
import asyncio
from stparts_browser_client import STPartsBrowserClient

async def test():
    async with STPartsBrowserClient(headless=False) as client:
        result = await client.search_part_with_retry("1351PK")
        print(result)

if __name__ == "__main__":
    asyncio.run(test())
