"""CAG (ADR-022, S14-3/4/5): antes de buscar no banco, a resposta já dada à mesma pergunta.

Escopo da chave: dono + geração dos dados do dono + reunião + pergunta anterior + pergunta, com o
texto normalizado (caixa, acentos e pontuação não contam). A geração sobe a cada gravação de
reunião ou nota do dono (reunião nova, resumo, tarefa, nomes, exclusão), o que invalida de uma
vez todas as respostas dele: a memória entre reuniões faz qualquer resposta depender de todas.

ponytail: "pergunta equivalente" = mesmo texto normalizado. Paráfrase por vetor ficou de fora:
"responsável pela tarefa A" e "pela tarefa B" dão vetores quase iguais e a resposta seria errada.
"""
from __future__ import annotations

import hashlib
import json
from typing import Optional

from use_cases.meeting_index import _norm

ANSWER_TTL = 24 * 3600


class AgentCache:
    def __init__(self, cache) -> None:
        self._cache = cache

    def _generation(self, owner_id: str) -> str:
        return self._cache.get(f"cag:gen:{owner_id}") or "0"

    def invalidate(self, owner_id: str) -> None:
        self._cache.incr(f"cag:gen:{owner_id}")

    def _key(self, owner_id: str, meeting_id: str, previous: str, question: str) -> str:
        asked = hashlib.sha1(f"{_norm(previous)}\n{_norm(question)}".encode()).hexdigest()
        return f"cag:ans:{owner_id}:{self._generation(owner_id)}:{meeting_id}:{asked}"

    def get(self, owner_id: str, meeting_id: str, previous: str, question: str) -> Optional[str]:
        raw = self._cache.get(self._key(owner_id, meeting_id, previous, question))
        return json.loads(raw)["answer"] if raw else None

    def put(self, owner_id: str, meeting_id: str, previous: str, question: str, answer: str) -> None:
        self._cache.set(self._key(owner_id, meeting_id, previous, question), json.dumps({"answer": answer}),
                        ANSWER_TTL)


class InvalidatingRepository:
    """O repositório de sempre; cada gravação ou exclusão de reunião invalida o cache do dono."""

    def __init__(self, repository, agent_cache: AgentCache) -> None:
        self._repo = repository
        self._cache = agent_cache

    def __getattr__(self, name):
        return getattr(self._repo, name)

    def save(self, meeting) -> None:
        self._repo.save(meeting)
        self._cache.invalidate(meeting.owner_id)

    def delete(self, meeting_id: str) -> None:
        meeting = self._repo.find_by_id(meeting_id)
        self._repo.delete(meeting_id)
        if meeting:
            self._cache.invalidate(meeting.owner_id)


class InvalidatingMemory:
    """Notas do usuário (memória procedural) mudam as respostas: gravar ou apagar invalida."""

    def __init__(self, store, agent_cache: AgentCache) -> None:
        self._store = store
        self._cache = agent_cache

    def __getattr__(self, name):
        return getattr(self._store, name)

    def add(self, note: dict) -> None:
        self._store.add(note)
        self._cache.invalidate(note.get("owner_id", ""))

    def delete(self, owner_id: str, note_id: str) -> bool:
        removed = self._store.delete(owner_id, note_id)
        self._cache.invalidate(owner_id)
        return removed
