"""
Collection Agent — Sincroniza reuniões do banco com a interface.

Fluxo:
  1. Polling consulta MongoDB e encontra meetings novos (mais recentes primeiro)
  2. Adiciona um por um na fila interna de requisições
  3. A cada input, alimenta o MemoryManager (curta/média/longa)
  4. Botão Refresh na UI drena a fila e exibe tudo
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Callable, Optional

from domain.entities.meeting import Meeting
from repositories.meeting_repository import IMeetingRepository
from agents.memory_manager import MemoryManager
from infrastructure.agents.db_admin_agent import DbAdminAgent


class CollectionAgent:
    """Agente que sincroniza reuniões do banco com a interface via fila."""

    def __init__(
        self,
        repository: IMeetingRepository,
        memory_manager: Optional[MemoryManager] = None,
        on_new_meeting: Optional[Callable[[Meeting], None]] = None,
        db_admin: Optional[DbAdminAgent] = None,
    ) -> None:
        self._repository = repository
        self._memory = memory_manager
        self._on_new_meeting = on_new_meeting
        self._db_admin = db_admin or DbAdminAgent()
        self._known_ids: set[str] = set()
        self._queue: list[Meeting] = []
        self._queue_lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self, interval: float = 10.0) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop,
            args=(interval,),
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def seed_ids(self, ids: list[str]) -> None:
        self._known_ids.update(ids)

    def poll(self) -> int:
        """Varre o banco e enfileira meetings novos (mais recentes primeiro)."""
        all_meetings = self._repository.list_all()
        new_meetings = [m for m in all_meetings if m.id not in self._known_ids]

        if not new_meetings:
            return 0

        new_meetings.sort(key=lambda m: m.started_at or datetime.min, reverse=True)

        count = 0
        with self._queue_lock:
            for meeting in new_meetings:
                self._known_ids.add(meeting.id)
                self._queue.append(meeting)
                count += 1
                if self._memory:
                    self._memory.on_input(meeting)
                if self._on_new_meeting:
                    self._on_new_meeting(meeting)
        return count

    def drain_queue(self) -> list[Meeting]:
        """Retorna todos os itens da fila e limpa."""
        with self._queue_lock:
            items = list(self._queue)
            self._queue.clear()
        return items

    @property
    def pending_count(self) -> int:
        with self._queue_lock:
            return len(self._queue)

    def get_new_meetings(self) -> list[Meeting]:
        return self.poll() > 0

    def consultar_por_id(self, original_id: str) -> Optional[dict]:
        """Retorna o documento mesclado (transcrição + legenda) de uma reunião.

        Consulta arquivos_mesclados — sem duplicatas, resultado único por reunião.
        Dispara o JOIN automaticamente se ainda não foi executado.
        """
        from pymongo import MongoClient
        import os
        uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017/meetagent")
        db_name = os.environ.get("MONGO_DB", "meetagent")
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        try:
            db = client[db_name]
            doc = db.arquivos_mesclados.find_one({"original_id": original_id})
            if doc:
                return doc
            # Ainda não mesclado — tenta executar o JOIN agora
            return self._db_admin.executar_e_validar(original_id)
        finally:
            client.close()

    def _poll_loop(self, interval: float) -> None:
        while self._running:
            try:
                self.poll()
            except Exception:
                pass
            time.sleep(interval)
