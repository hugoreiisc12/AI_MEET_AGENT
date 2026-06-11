import sys, asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from infrastructure.mongodb_documents import MeetingDocument

async def main():
    client = AsyncIOMotorClient('mongodb://localhost:27017/meetagent')
    await init_beanie(database=client.meetagent, document_models=[MeetingDocument])
    docs = await MeetingDocument.find_all().to_list()
    print(f'Total de documentos: {len(docs)}')
    for d in docs:
        print(f'  ID: {d.id}')
        print(f'  Titulo: {d.title}')
        print(f'  Participantes: {d.participants}')
        print(f'  Duracao: {d.duration_minutes} min')
        print(f'  Transcricao: {len(d.transcript_text or "")} chars')
        print(f'  Summary: {"SIM" if d.summary else "NAO"}')
        if d.summary:
            print(f'    Overview: {d.summary.overview[:80]}...')
            print(f'    Topicos: {len(d.summary.topics)}')
            print(f'    Tarefas: {len(d.summary.tasks)}')
            for t in d.summary.tasks:
                print(f'      - {t.description[:60]} / {t.responsible} / {t.deadline}')
            print(f'    Decisoes: {len(d.summary.decisions)}')
            for dec in d.summary.decisions:
                print(f'      - {dec.description[:60]}')
        print()
    client.close()

asyncio.run(main())
