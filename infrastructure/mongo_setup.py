# MongoDb funcionando como repostiorio de dados para reuniões, resumos, tarefas e decisões.
import asyncio
import logging
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient

from infrastructure.mongo_documents import (
    MeetingDocument,
    SummaryDocument,
    TaskDocument,
    DecisionDocument,
)

logger = logging.getLogger(__name__)

_client: Optional[AsyncIOMotorClient] = None
_initialized: bool = False
_loop: Optional[asyncio.AbstractEventLoop] = None


def _get_loop() -> asyncio.AbstractEventLoop:
    global _loop
    if _loop is None or _loop.is_closed():
        import sys
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
    return _loop


def init_mongo(mongo_uri: str, db_name: str) -> None:
    global _client, _initialized

    if _initialized:
        return

    try:
        from beanie import init_beanie

        _client = AsyncIOMotorClient(
            mongo_uri,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
        )

        async def _init():
            await init_beanie(
                database=_client[db_name],
                document_models=[
                    MeetingDocument,
                    SummaryDocument,
                    TaskDocument,
                    DecisionDocument,
                ],
            )

        loop = _get_loop()
        loop.run_until_complete(_init())
        _initialized = True
        logger.info("MongoDB initialized successfully: %s/%s", mongo_uri, db_name)
    except Exception as e:
        _initialized = False
        logger.error("Failed to initialize MongoDB: %s", e)
        raise


def is_mongo_available() -> bool:
    return _initialized and _client is not None


def get_client() -> Optional[AsyncIOMotorClient]:
    return _client


def shutdown_mongo() -> None:
    global _client, _initialized, _loop

    if _client:
        try:
            loop = _get_loop()
            loop.run_until_complete(_client.close())
        except Exception:
            pass
        _client = None
    _initialized = False
    if _loop and not _loop.is_closed():
        _loop.close()
    _loop = None
