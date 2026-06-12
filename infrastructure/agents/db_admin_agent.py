"""
db_admin_agent.py — Administrador de banco que realiza o INNER JOIN entre
transcrição (Whisper) e legenda (CC) de uma mesma reunião.

Fluxo:
  1. Busca `tipo=transcricao` e `tipo=legenda` com mesmo `original_id`
  2. Se ambos existirem → mescla em `arquivos_mesclados`
  3. Valida que o documento foi inserido
  4. Retorna o documento mesclado ou None se o JOIN falhou
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional

from pymongo import MongoClient
from pymongo.database import Database

logger = logging.getLogger(__name__)


class DbAdminAgent:
    def __init__(
        self,
        mongo_uri: str | None = None,
        db_name: str | None = None,
    ) -> None:
        uri = mongo_uri or os.environ.get("MONGO_URI", "mongodb://localhost:27017/meetagent")
        name = db_name or os.environ.get("MONGO_DB", "meetagent")
        self._client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        self._db: Database = self._client[name]

    # ------------------------------------------------------------------
    # INNER JOIN principal
    # ------------------------------------------------------------------

    def inner_join_transcricao_legenda(self, original_id: str) -> Optional[dict]:
        """
        Busca transcrição e legenda com mesmo original_id e mescla em
        arquivos_mesclados. Retorna None se um dos documentos não existir
        (comportamento INNER JOIN — sem match, sem resultado).
        """
        transcricao = self._db.arquivos.find_one({
            "original_id": original_id,
            "tipo": "transcricao",
        })
        legenda = self._db.arquivos.find_one({
            "original_id": original_id,
            "tipo": "legenda",
        })

        if not transcricao or not legenda:
            logger.warning(
                "INNER JOIN incompleto para %s — transcricao=%s legenda=%s",
                original_id,
                bool(transcricao),
                bool(legenda),
            )
            return None

        documento_mesclado = {
            "original_id": original_id,
            "meta": {
                "arquivo_transcricao": f"arquivo{original_id}.json",
                "arquivo_legenda": f"arquivo{original_id}.json2",
                "mesclado_em": datetime.now().isoformat(),
            },
            "transcricao": {
                "original_id": str(transcricao["_id"]),
                "tipo": transcricao["tipo"],
                "conteudo": transcricao["conteudo"],
            },
            "legenda": {
                "original_id": str(legenda["_id"]),
                "tipo": legenda["tipo"],
                "conteudo": legenda["conteudo"],
            },
        }

        resultado = self._db.arquivos_mesclados.insert_one(documento_mesclado)
        logger.info("Mesclagem concluída — original_id=%s _id=%s", original_id, resultado.inserted_id)

        return {
            "_id": str(resultado.inserted_id),
            "original_id": original_id,
            "transcricao": documento_mesclado["transcricao"],
            "legenda": documento_mesclado["legenda"],
        }

    # ------------------------------------------------------------------
    # Validação
    # ------------------------------------------------------------------

    def validar_mesclagem(self, original_id: str) -> bool:
        doc = self._db.arquivos_mesclados.find_one({"original_id": original_id})
        ok = doc is not None
        logger.info("Validação de mesclagem — original_id=%s ok=%s", original_id, ok)
        return ok

    def executar_e_validar(self, original_id: str) -> Optional[dict]:
        """Executa o JOIN e confirma a inserção em sequência."""
        resultado = self.inner_join_transcricao_legenda(original_id)
        if resultado is None:
            logger.error("JOIN falhou para %s — dados incompletos no banco", original_id)
            return None
        if not self.validar_mesclagem(original_id):
            logger.error("Validação falhou para %s — documento não encontrado", original_id)
            return None
        logger.info("JOIN + validação OK para %s", original_id)
        return resultado

    def close(self) -> None:
        self._client.close()