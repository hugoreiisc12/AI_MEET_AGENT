"""
postgres_meeting_repository.py — Adaptador Postgres para modo colaborativo.

Implementa IMeetingRepository usando SQLAlchemy async.
Instanciado pelo CollabContainer automaticamente quando APP_MODE=collab.

Para usar:
    pip install sqlalchemy asyncpg alembic
    DATABASE_URL=postgresql+asyncpg://user:pass@host/db
"""

from typing import Optional
from domain.entities.meeting import Meeting
from domain.repositories.meeting_repository import IMeetingRepository


class PostgresMeetingRepository(IMeetingRepository):
    """
    Repositório Postgres — mesmo contrato que JsonMeetingRepository.
    Nenhuma linha de use_case ou domain muda ao trocar de adaptador.
    """

    def __init__(self, database_url: str) -> None:
        self._url = database_url
        self._engine = None
        # SQLAlchemy engine criado lazy na primeira operação
        # para evitar falha se Postgres não estiver disponível no import

    def _get_engine(self):
        if self._engine is None:
            try:
                from sqlalchemy import create_engine
                self._engine = create_engine(
                    self._url.replace("+asyncpg", ""),  # sync para simplicidade inicial
                    pool_size=5,
                    max_overflow=10,
                )
            except ImportError:
                raise RuntimeError(
                    "sqlalchemy não instalado. Execute: pip install sqlalchemy asyncpg"
                )
        return self._engine

    def save(self, meeting: Meeting) -> None:
        # TODO: implementar com SQLAlchemy ORM
        # Session + upsert na tabela meetings
        raise NotImplementedError(
            "PostgresMeetingRepository.save() — aguardando migrations Alembic.\n"
            "Para desenvolvimento, use APP_MODE=solo com JsonMeetingRepository."
        )

    def find_by_id(self, meeting_id: str) -> Optional[Meeting]:
        raise NotImplementedError("Aguardando migrations Alembic.")

    def list_all(self) -> list[Meeting]:
        raise NotImplementedError("Aguardando migrations Alembic.")

    def delete(self, meeting_id: str) -> None:
        raise NotImplementedError("Aguardando migrations Alembic.")