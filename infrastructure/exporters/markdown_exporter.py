"""
infrastructure/exporters/markdown_exporter.py

Exporta reunião como arquivo Markdown estruturado.
Funciona sem nenhuma API externa — útil para modo solo
e como base para os outros exporters.
"""

from pathlib import Path
from datetime import datetime
from domain.entities.meeting import Meeting
from domain.interfaces.exporter import IExporter, ExportError


class MarkdownExporter(IExporter):
    """Exporta reunião para arquivo .md local."""

    def __init__(self, output_dir: str = "data/exports") -> None:
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def name(self) -> str:
        return "Markdown"

    def export(self, meeting: Meeting) -> str:
        try:
            content = self._build_markdown(meeting)
            safe_title = "".join(c for c in meeting.title if c.isalnum() or c in " -_").strip()
            filename = f"{safe_title}_{meeting.started_at.strftime('%Y%m%d_%H%M')}.md"
            path = self._output_dir / filename

            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

            return str(path)

        except Exception as e:
            raise ExportError(f"Markdown export falhou: {str(e)}") from e

    def _build_markdown(self, meeting: Meeting) -> str:
        lines = []
        lines.append(f"# {meeting.title}")
        lines.append(f"\n**Data:** {meeting.started_at.strftime('%-d de %B de %Y às %H:%M')}")
        lines.append(f"**Duração:** {meeting.duration_minutes:.0f} minutos")

        if meeting.participants:
            lines.append(f"**Participantes:** {', '.join(meeting.participants)}")

        if meeting.summary:
            s = meeting.summary
            lines.append(f"\n## Visão Geral\n\n{s.overview}")

            if s.topics:
                lines.append("\n## Tópicos Discutidos\n")
                for t in s.topics:
                    lines.append(f"- {t}")

            if s.tasks:
                lines.append("\n## Tarefas\n")
                for task in s.tasks:
                    check = "x" if task.done else " "
                    lines.append(
                        f"- [{check}] **{task.description}** — {task.responsible} ({task.deadline})"
                    )

            if s.decisions:
                lines.append("\n## Decisões\n")
                for dec in s.decisions:
                    lines.append(f"- **{dec.description}**")
                    if dec.context:
                        lines.append(f"  > {dec.context}")

        if meeting.transcript_formatted or meeting.transcript_text:
            lines.append("\n## Transcrição Completa\n")
            lines.append("```")
            lines.append(meeting.transcript_formatted or meeting.transcript_text)
            lines.append("```")

        lines.append(f"\n---\n*Gerado por Meet Agent em {datetime.now().strftime('%d/%m/%Y %H:%M')}*")
        return "\n".join(lines)