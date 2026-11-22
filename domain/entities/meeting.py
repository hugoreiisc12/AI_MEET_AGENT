from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class MeetingStatus(str, Enum):
    """Etapa do processamento. Única fonte de status do sistema."""
    PENDING = "pending"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    SUMMARIZING = "summarizing"
    DONE = "done"
    ERROR = "error"


@dataclass
class Task:
    description: str
    responsible: str = "Não definido"
    deadline: Optional[str] = None
    done: bool = False

    def __str__(self) -> str:
        status = "✅" if self.done else "⬜"
        return f"{status} {self.description} — {self.responsible} ({self.deadline})"


@dataclass
class Decision:
    description: str
    context: str = ""
    # §7 do contrato: aprovada, condicionada, proposta, pendente, rejeitada ou inconclusiva.
    # Vazio = resumo anterior ao contrato (ADR-014).
    status: str = ""

    def __str__(self) -> str:
        return f"• {self.description}" + (f" [{self.status}]" if self.status else "")


@dataclass
class Summary:
    overview: str = ""
    topics: list[str] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    # Contrato v2 (S15-4): o que cada um trouxe {"speaker", "points"}, que tópico pesou em que decisão
    # {"topic", "decision", "effect"} e o que ficou sem resposta. Vazios em resumos anteriores.
    contributions: list[dict] = field(default_factory=list)
    topic_decisions: list[dict] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)

    @property
    def has_tasks(self) -> bool:
        return len(self.tasks) > 0

    @property
    def pending_tasks(self) -> list[Task]:
        return [t for t in self.tasks if not t.done]

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

        if self.topic_decisions:
            lines.append("\n## Tópicos e decisões")
            lines += [f"- {t['topic']} → {t['decision']}" + (f" ({t['effect']})" if t.get("effect") else "")
                      for t in self.topic_decisions]

        if self.contributions:
            lines.append("\n## Contribuições por participante")
            lines += [f"- {c['speaker']}: " + "; ".join(c["points"]) for c in self.contributions]

        if self.open_questions:
            lines.append("\n## Questões em aberto")
            lines += [f"- {q}" for q in self.open_questions]

        return "\n".join(lines)


@dataclass
class Meeting:
    id: str
    title: str
    # Dono da reunião (id do usuário). Vazio = anterior ao login multiusuário (ADR-011).
    owner_id: str = ""
    # Plataforma de origem ("meet", "teams", "zoom"); vazio para áudio enviado.
    platform: str = ""
    # Link normalizado da reunião (bot); identifica "a mesma reunião" entre usuários.
    meeting_url: str = ""
    # Outro usuário já mandou o bot a este link: esta reunião espera a gravação dele
    # e recebe uma cópia do resultado (ADR-011). Vazio depois de copiada.
    source_id: str = ""
    started_at: datetime = field(default_factory=datetime.now)
    audio_path: Optional[str] = None
    transcript_text: str = ""
    transcript_formatted: str = ""
    summary: Optional[Summary] = None
    participants: list[str] = field(default_factory=list)
    duration_minutes: float = 0.0
    transcript_raw: str = ""
    status: MeetingStatus = MeetingStatus.PENDING
    # Quando o status atual começou (para a tela mostrar há quanto tempo a etapa roda e perceber
    # trava). Preenchido sozinho na criação e a cada troca de status (__setattr__).
    status_at: Optional[datetime] = None
    error: str = ""
    # Conversa do chat sobre esta reunião: [{"role": "user"|"assistant", "content": str}]
    chat_history: list[dict] = field(default_factory=list)
    # Medições do processamento (tempos em segundos, tamanho da transcrição). Ver ADR-010.
    metrics: dict = field(default_factory=dict)
    # Esperando um worker (ADR-015): fila "transcribe" ou "llm"; vazio quando não está na fila.
    # A ordem de atendimento é (queue_priority, queued_at); 0 é a maior prioridade.
    queue: str = ""
    queue_priority: int = 0
    queued_at: Optional[datetime] = None

    def __post_init__(self):
        if self.status_at is None:  # reunião nova (ou documento antigo sem o campo): conta de agora
            object.__setattr__(self, "status_at", datetime.now())

    def __setattr__(self, name, value):
        if name == "status" and getattr(self, "status", None) != value:
            object.__setattr__(self, "status_at", datetime.now())
        object.__setattr__(self, name, value)

    @property
    def participants_header(self) -> str:
        """Lista de presentes, para o LLM saber quem estava na reunião mesmo
        que alguém não tenha falado. Vazio quando não se sabe."""
        if not self.participants:
            return ""
        return f"PARTICIPANTES DA REUNIÃO: {', '.join(self.participants)}\n\n"

    @property
    def transcript_for_llm(self) -> str:
        return self.participants_header + (self.transcript_formatted or self.transcript_text)

    @property
    def is_transcribed(self) -> bool:
        return bool(self.transcript_text)

    @property
    def is_summarized(self) -> bool:
        return self.summary is not None
