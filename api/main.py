"""
api/main.py — FastAPI para modo colaborativo.

Endpoints:
  POST /meetings/upload   → recebe áudio, enfileira processamento
  GET  /meetings/{id}     → retorna reunião processada
  GET  /meetings/{id}/status → status do processamento
  POST /meetings/{id}/chat   → pergunta ao agente
  GET  /meetings           → lista reuniões do usuário
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import get_settings
from api.routers import meetings
from api import chat

settings = get_settings()

app = FastAPI(
    title="Meet Agent API",
    description="API colaborativa do agente de reuniões",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(meetings.router, prefix="/meetings", tags=["meetings"])
app.include_router(chat.router, prefix="/meetings", tags=["chat"])


@app.on_event("startup")
async def startup():
    if settings.is_collab:
        from motor.motor_asyncio import AsyncIOMotorClient
        from beanie import init_beanie
        from infrastructure.mongodb_documents import MeetingDocument
        client = AsyncIOMotorClient(settings.mongo_uri)
        await init_beanie(
            database=client[settings.mongo_db],
            document_models=[MeetingDocument],
        )


@app.get("/health")
def health():
    return {"status": "ok", "mode": settings.app_mode}