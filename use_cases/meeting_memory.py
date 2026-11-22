"""Memória entre reuniões (§14 do contrato), por dono.

Duas fontes, nenhuma inventada pelo modelo:
- continuidade: decisões (com o estado) e tarefas abertas dos resumos já gravados das OUTRAS
  reuniões do mesmo dono, cada item com data e título de origem e se veio antes ou depois;
- notas: o que o usuário pediu para lembrar ("prefiro atas em tópicos"), via ferramenta remember.

Entra no contexto do chat só o que tem a ver com a pergunta e com a reunião aberta, até
MAX_CHARS. Itens de reunião antiga não são tratados como vigentes: o bloco diz isso ao modelo.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from domain.entities.meeting import Meeting
from use_cases.llm_context import _words

MAX_CHARS = 4000
MAX_OPEN_TASKS = 8     # pendências abertas entram mesmo sem palavra em comum (são "o que ficou")
MAX_NOTES = 30


@dataclass
class MemoryItem:
    kind: str           # "decisão" | "tarefa aberta" | "questão em aberto"
    text: str
    meeting: Meeting

    def line(self, current: Meeting) -> str:
        when = "REUNIÃO ANTERIOR" if self.meeting.started_at <= current.started_at else "REUNIÃO POSTERIOR"
        return (f"- [{when}: \"{self.meeting.title}\", {self.meeting.started_at:%d/%m/%Y}] "
                f"{self.kind}: {self.text}")


def _items(meeting: Meeting) -> list[MemoryItem]:
    if not meeting.summary:
        return []
    items = [MemoryItem(f"decisão ({d.status or 'sem estado'})", d.description, meeting)
             for d in meeting.summary.decisions]
    items += [MemoryItem("tarefa aberta", f"{t.description} — responsável: {t.responsible}"
                         + (f" — prazo: {t.deadline}" if t.deadline else ""), meeting)
              for t in meeting.summary.tasks if not t.done]
    items += [MemoryItem("questão em aberto", q, meeting) for q in meeting.summary.open_questions]
    return items


def build_memory(current: Meeting, others: list[Meeting], notes: list[dict], question: str,
                 max_chars: int = MAX_CHARS) -> str:
    """Bloco de memória para o contexto do chat. Vazio se não há nada para lembrar."""
    parts = []
    if notes:
        lines = "\n".join(f"- {n['text']}" for n in notes[-MAX_NOTES:])
        parts.append("NOTAS QUE O USUÁRIO PEDIU PARA VOCÊ LEMBRAR (valem para todas as reuniões dele):\n"
                     + lines)

    topic = question + " " + (current.summary.overview if current.summary else "") + " " + \
        " ".join(current.summary.topics if current.summary else [])
    wanted = _words(topic)
    scored = []
    for m in others:
        if m.id == current.id or m.source_id:
            continue
        for item in _items(m):
            overlap = len(wanted & _words(item.text))
            if overlap or item.kind in ("tarefa aberta", "questão em aberto"):
                scored.append((overlap, m.started_at, item))
    # Mais palavras em comum primeiro; empate, a mais recente. Tarefas abertas sem assunto em
    # comum ficam limitadas, para não encher o contexto com pendência de outro projeto.
    scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
    lines, size, loose_tasks = [], 0, 0
    for overlap, _, item in scored:
        if not overlap:
            if loose_tasks >= MAX_OPEN_TASKS:
                continue
            loose_tasks += 1
        line = item.line(current)
        if size + len(line) > max_chars:
            break
        lines.append(line)
        size += len(line)
    if lines:
        parts.append(
            "REGISTROS DE OUTRAS REUNIÕES DO MESMO USUÁRIO (§14). Nenhum destes itens é da reunião aberta: "
            "são resumos gravados de reuniões ANTERIORES ou POSTERIORES a ela, como marcado em cada linha. "
            "Ao usar um item, diga de qual reunião e data veio. Decisão de reunião anterior pode ter sido "
            "revista depois; decisão de reunião posterior revê a da reunião aberta. Se precisar de uma "
            "reunião que não está aqui, diga que não tem acesso a ela.\n"
            + "\n".join(lines))
    elif others:
        parts.append("Não há, nas outras reuniões deste usuário, registro ligado a esta pergunta.")
    return ("\n\n".join(parts) + "\n\n") if parts else ""


def new_note(owner_id: str, text: str, meeting_id: str = "") -> Optional[dict]:
    text = " ".join(text.split())[:500]
    if not text:
        return None
    import uuid
    return {"_id": uuid.uuid4().hex[:12], "owner_id": owner_id, "text": text, "meeting_id": meeting_id,
            "created_at": datetime.now()}
