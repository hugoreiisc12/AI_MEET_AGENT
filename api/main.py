"""
api/main.py — FastAPI para modo colaborativo.

Endpoints:
  POST /meetings/upload   → recebe áudio, enfileira processamento
  GET  /meetings/{id}     → retorna reunião processada
  GET  /meetings/{id}/status → status do processamento
  POST /meetings/{id}/chat   → pergunta ao agente
  GET  /meetings           → lista reuniões do usuário
"""

# Importa módulos do sistema para manipulação de caminhos
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Importa FastAPI e dependências de middleware e tratamento HTTP
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware

# Importa configurações da aplicação e roteadores da API
from config.settings import get_settings
from api.routers import meetings, chat

# Obtém as configurações da aplicação
settings = get_settings()

# Cria a aplicação FastAPI com metadados
app = FastAPI(
    title="Meet Agent API",
    description="API colaborativa do agente de reuniões",
    version="1.0.0",
)

# Adiciona middleware CORS para permitir requisições cross-origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,  # Origens permitidas das configurações
    allow_credentials=True,  # Permite envio de credenciais
    allow_methods=["*"],  # Permite todos os métodos HTTP
    allow_headers=["*"],  # Permite todos os headers
)

# Inclui rotas de reuniões e chat no prefixo /meetings
app.include_router(meetings.router, prefix="/meetings", tags=["meetings"])
app.include_router(chat.router, prefix="/meetings", tags=["chat"])


# Endpoint de saúde que retorna o status da API
@app.get("/health")
def health():
    # Retorna status OK e o modo da aplicação (collab ou solo)
    return {"status": "ok", "mode": settings.app_mode}