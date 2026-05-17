from abc import ABC, abstractmethod
from entities.metting import Meeting


class IExporter(ABC):
    """Contrato para exportação de reuniões para sistemas externos."""

    @abstractmethod
    def export(self, meeting: Meeting) -> str:
        """
        Exporta a reunião e retorna uma URL ou caminho do documento criado.

        Args:
            meeting: Meeting com transcrição e resumo

        Returns:
            URL ou path do documento exportado

        Raises:
            ExportError: se a exportação falhar
        """
        ...

    @abstractmethod
    def name(self) -> str:
        """Nome do exportador para exibição na UI (ex: 'Notion', 'Google Docs')."""
        ...


class ExportError(Exception):
    pass