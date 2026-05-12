# Entidades de domínio que representam reunião, tarefas, decisões e resumos
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# Representa uma tarefa identificada em reunião
@dataclass
class Task:
    """Tarefa com descrição, responsável e prazo."""
    description: str  # Descrição detalhada da tarefa
    responsible: str = "Não definido"  # Quem é responsável
    deadline: Optional[str] = None  # Prazo (ex: "15/02/2024")
    done: bool = False  # Se foi concluída

    # Formata tarefa com status visual
    def __str__(self) -> str:
        status = "✅" if self.done else "⬜"
        return f"{status} {self.description} — {self.responsible} ({self.deadline})"


# Representa uma decisão tomada durante reunião
@dataclass
class Decision:
    """Decisão com descrição e contexto."""
    description: str  # Descrição da decisão
    context: str = ""  # Contexto e motivo

    # Formata decisão para exibição
    def __str__(self) -> str:
        return f"• {self.description}"


# Representa resumo estruturado de reunião
@dataclass
class Summary:
    """Resumo gerado por LLM com tópicos, tarefas e decisões."""
    overview: str = ""  # Parágrafo resumindo reunião
    topics: list[str] = field(default_factory=list)  # Tópicos discutidos
    tasks: list[Task] = field(default_factory=list)  # Tarefas identificadas
    decisions: list[Decision] = field(default_factory=list)  # Decisões tomadas
    created_at: datetime = field(default_factory=datetime.now)  # Quando foi criado

    # Verifica se tem tarefas
    @property
    def has_tasks(self) -> bool:
        return len(self.tasks) > 0

    # Retorna apenas tarefas não concluídas
    @property
    def pending_tasks(self) -> list[Task]:
        return [t for t in self.tasks if not t.done]

    # Formata resumo com estrutura visual
    @property
    def formatted(self) -> str:
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


# Entidade central que representa uma reunião completa
@dataclass
class Meeting:
    """Reunião com transcrição, resumo e metadados."""
    id: str  # ID único da reunião
    title: str  # Título da reunião
    started_at: datetime = field(default_factory=datetime.now)  # Quando iniciou
    audio_path: Optional[str] = None  # Caminho do arquivo de áudio
    transcript_text: str = ""  # Transcrição em texto simples
    transcript_formatted: str = ""  # Transcrição formatada com speakers
    summary: Optional[Summary] = None  # Resumo gerado por LLM
    participants: list[str] = field(default_factory=list)  # Participantes
    duration_minutes: float = 0.0  # Duração em minutos

    # Verifica se foi transcrita
    @property
    def is_transcribed(self) -> bool:
        return bool(self.transcript_text)

    # Verifica se foi sumarizada
    @property
    def is_summarized(self) -> bool:
        return self.summary is not None
