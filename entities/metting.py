# Entidade que representa uma reunião, suas tarefas, decisões e resumo gerado por LLM.
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ========== TASK ==========
@dataclass
class Task:
    """Uma tarefa identificada em reunião, com descrição, responsável, prazo e status de conclusão."""
    description: str
    responsible: str = "Não definido"
    deadline: Optional[str] = None
    done: bool = False 

    def __str__(self) -> str:
        status = "✅" if self.done else "⬜"
        return f"{status} {self.description} — {self.responsible} ({self.deadline})"


# ========== DECISION ==========
@dataclass
class Decision:
    """Uma decisão tomada durante a reunião, com descrição e contexto."""
    description: str
    context: str = ""

    def __str__(self) -> str:
        return f"• {self.description}"


# ========== SUMMARY ==========
@dataclass
class Summary:
    """Resumo estruturado de uma reunião gerada por LLM."""
    overview: str = ""
    topics: list[str] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def has_tasks(self) -> bool:
        """Verifica se existem tarefas no resumo."""
        return len(self.tasks) > 0

    @property
    def pending_tasks(self) -> list[Task]:
        """Retorna apenas tarefas que não foram concluídas."""
        return [t for t in self.tasks if not t.done]

    @property
    def formatted(self) -> str:
        """Formata o resumo para exibição legível."""
        lines = []

        if self.overview:
            lines.append("## Visão Geral")
            lines.append(self.overview)

        if self.topics:
            lines.append("\n## Tópicos Discutidos")
            for topic in self.topics:
                lines.append(f"- {topic}")

        if self.tasks:
            lines.append("\n## Tarefas")
            for task in self.tasks:
                lines.append(str(task))

        if self.decisions:
            lines.append("\n## Decisões Tomadas")
            for decision in self.decisions:
                lines.append(str(decision))

        return "\n".join(lines)


# MEETING 
@dataclass
class Meeting:
    """Entidade central - agrega transcrição, decisões e tarefas de uma reunião."""
    id: str
    title: str
    started_at: datetime = field(default_factory=datetime.now)
    audio_path: Optional[str] = None
    transcript_text: str = ""
    transcript_formatted: str = ""
    summary: Optional[Summary] = None
    participants: list[str] = field(default_factory=list)
    duration_minutes: float = 0.0

    @property
    def is_transcribed(self) -> bool:
        """Verifica se a reunião foi transcrita."""
        return bool(self.transcript_text)

    @property
    def is_summarized(self) -> bool:
        """Verifica se a reunião foi sumarizada por LLM."""
        return self.summary is not None
