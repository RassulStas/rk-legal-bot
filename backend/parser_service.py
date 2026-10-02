import asyncio
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("parser_service")

async def fetch_latest_rk_laws():
    while True:
        try:
            logger.info(f"Запуск фоновой проверки обновлений законодательства РК...")
            await asyncio.sleep(3600)
        except Exception as e:
            logger.error(f"Ошибка в работе парсера Әділет: {e}")
            await asyncio.sleep(60)

def start_background_parser():
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(fetch_latest_rk_laws())
    except RuntimeError:
        loop = asyncio.get_event_loop()
        loop.create_task(fetch_latest_rk_laws())
