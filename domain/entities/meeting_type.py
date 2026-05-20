"""Enum para tipos de reunião com rótulos e áreas de foco."""

from enum import Enum


class MeetingType(str, Enum):
    """
    Tipos de reuniões corporativas.
    
    Cada tipo tem um rótulo humanizado e áreas de foco específicas
    para guiar a sumarização e análise pelo LLM.
    """

    GENERAL = "general"
    PLANNING = "planning"
    RETROSPECTIVE = "retrospective"
    ONE_ON_ONE = "one_on_one"
    REVIEW = "review"
    INTERVIEW = "interview"
    BRAINSTORM = "brainstorm"

    @property
    def label(self) -> str:
        """Rótulo humanizado do tipo de reunião."""
        labels = {
            MeetingType.GENERAL: "Geral",
            MeetingType.PLANNING: "Planejamento",
            MeetingType.RETROSPECTIVE: "Retrospectiva",
            MeetingType.ONE_ON_ONE: "1:1",
            MeetingType.REVIEW: "Review / Demo",
            MeetingType.INTERVIEW: "Entrevista",
            MeetingType.BRAINSTORM: "Brainstorm",
        }
        return labels.get(self, "Geral")

    @property
    def focus_areas(self) -> list[str]:
        """Áreas de foco específicas para este tipo de reunião."""
        areas = {
            MeetingType.GENERAL: ["Tópicos", "Decisões", "Ações", "Próximos passos"],
            MeetingType.PLANNING: ["Objetivos", "Tarefas", "Riscos", "Dependências"],
            MeetingType.RETROSPECTIVE: ["Successo", "Melhorias", "Ações", "Aprendizados"],
            MeetingType.ONE_ON_ONE: ["Feedback", "Desenvolvimento", "Bem-estar", "Metas"],
            MeetingType.REVIEW: ["Entregas", "Feedbacks", "Demos", "Bloqueadores"],
            MeetingType.INTERVIEW: ["Experiência", "Habilidades", "Cultura", "Recomendação"],
            MeetingType.BRAINSTORM: ["Ideias", "Validação", "Priorização", "Próximos passos"],
        }
        return areas.get(self, [])

    def __str__(self) -> str:
        return self.label
