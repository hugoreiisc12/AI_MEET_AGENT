import sys, asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from infrastructure.mongodb_documents import MeetingDocument

async def main():
    client = AsyncIOMotorClient('mongodb://localhost:27017/meetagent')
    await init_beanie(database=client.meetagent, document_models=[MeetingDocument])
    doc = await MeetingDocument.get('REUNIAO-2026-06-09-001')
    if doc:
        await doc.delete()
        print(f'[OK] Reuniao REUNIAO-2026-06-09-001 deletada')
    else:
        print(f'[SKIP] Reuniao nao encontrada')
    client.close()

asyncio.run(main())
