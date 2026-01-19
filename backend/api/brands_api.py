"""
API для получения списка брендов с ZZAP.

Использует глобальный ZZAP клиент для быстрого получения брендов по артикулу.
"""

from fastapi import APIRouter, HTTPException
from typing import List
import sys
from pathlib import Path
import logging
import asyncio

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from zzap_cdp_client import ZZapCDPClient

logger = logging.getLogger(__name__)
router = APIRouter()

# Глобальный ZZAP клиент (инициализируется при первом запросе)
_zzap_client: ZZapCDPClient = None
_client_lock = asyncio.Lock()


async def get_zzap_client() -> ZZapCDPClient:
    """Получить или создать глобальный ZZAP клиент."""
    global _zzap_client

    async with _client_lock:
        if _zzap_client is None or not _zzap_client.is_connected:
            logger.info("[brands_api] Инициализация ZZAP клиента...")
            _zzap_client = ZZapCDPClient()
            connected = await _zzap_client.connect()
            if not connected:
                raise HTTPException(status_code=503, detail="Не удалось подключиться к ZZAP")
            logger.info("[brands_api] ZZAP клиент готов")

    return _zzap_client


@router.get("/brands")
async def get_brands(partnumber: str) -> List[str]:
    """Получить список брендов для артикула с ZZAP.

    Args:
        partnumber: Артикул для поиска

    Returns:
        Список брендов (например: ['TOYOPOWER', 'TRIALLI', 'GATES'])
    """
    if not partnumber or len(partnumber) < 2:
        raise HTTPException(status_code=400, detail="Артикул должен содержать минимум 2 символа")

    try:
        client = await get_zzap_client()
        brands = await client.get_brands_for_partnumber(partnumber.strip())

        if not brands:
            logger.info(f"[brands_api] Бренды не найдены для: {partnumber}")
            return []

        logger.info(f"[brands_api] Найдено {len(brands)} брендов для {partnumber}: {brands}")
        return brands

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[brands_api] Ошибка получения брендов: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")


@router.on_event("shutdown")
async def shutdown_zzap_client():
    """Закрыть ZZAP клиент при завершении."""
    global _zzap_client
    if _zzap_client:
        await _zzap_client.close()
        _zzap_client = None
        logger.info("[brands_api] ZZAP клиент закрыт")
