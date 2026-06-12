"""
storage_arquivos.py — Inserção e consulta na coleção `arquivos` do MongoDB.

Cada reunião gera dois documentos com o mesmo `original_id`:
  - tipo "transcricao": saída do Whisper sobre o .webm
  - tipo "legenda":     legendas capturadas do CC do Google Meet
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional

from pymongo import MongoClient
from pymongo.collection import Collection

logger = logging.getLogger(__name__)


class ArquivosStorage:
    def __init__(
        self,
        mongo_uri: str | None = None,
        db_name: str | None = None,
    ) -> None:
        uri = mongo_uri or os.environ.get("MONGO_URI", "mongodb://localhost:27017/meetagent")
        name = db_name or os.environ.get("MONGO_DB", "meetagent")
        self._client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        self._col: Collection = self._client[name]["arquivos"]

    # ------------------------------------------------------------------
    # Inserção
    # ------------------------------------------------------------------

    def inserir_transcricao(self, original_id: str, conteudo: dict) -> str:
        """Persiste a transcrição Whisper do .webm."""
        doc = {
            "original_id": original_id,
            "tipo": "transcricao",
            "conteudo": conteudo,
            "created_at": datetime.now().isoformat(),
        }
        result = self._col.insert_one(doc)
        logger.info("Transcrição inserida — original_id=%s _id=%s", original_id, result.inserted_id)
        return str(result.inserted_id)

    def inserir_legenda(self, original_id: str, conteudo: list) -> str:
        """Persiste as legendas CC capturadas pelo bot."""
        doc = {
            "original_id": original_id,
            "tipo": "legenda",
            "conteudo": conteudo,
            "created_at": datetime.now().isoformat(),
        }
        result = self._col.insert_one(doc)
        logger.info("Legenda inserida — original_id=%s _id=%s", original_id, result.inserted_id)
        return str(result.inserted_id)

    # ------------------------------------------------------------------
    # Consulta
    # ------------------------------------------------------------------

    def buscar(self, original_id: str, tipo: str) -> Optional[dict]:
        return self._col.find_one({"original_id": original_id, "tipo": tipo})

    def ambos_disponiveis(self, original_id: str) -> bool:
        t = self.buscar(original_id, "transcricao")
        l = self.buscar(original_id, "legenda")
        return t is not None and l is not None

    def close(self) -> None:
        self._client.close()