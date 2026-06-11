import logging
from typing import Optional

from domain.entities.meeting import Meeting
from repositories.meeting_repository import IMeetingRepository

logger = logging.getLogger(__name__)


class ValidationQueryAgent:
    """Agente de validação e consulta de reuniões do banco.

    Responsável por:
    1. Validar se existem reuniões salvas no banco que não existam na
       interface Streamlit (comparar as duas listas).
    2. Se houver reuniões faltando, consultar e puxar todas do banco.
    3. Retornar as reuniões para serem exibidas no histórico do Streamlit.

    Fluxo:
        1. Recebe a lista de IDs atualmente carregados na interface
           (ids_interface)
        2. Busca todos os IDs existentes no banco via IMeetingRepository
        3. Compara os dois conjuntos
        4. Retorna as reuniões que estão no banco mas não na interface
        5. Retorna também uma lista completa se solicitado
    """

    def __init__(self, repository: IMeetingRepository) -> None:
        self._repository = repository

    def find_missing_meetings(
        self,
        ids_in_interface: set[str],
    ) -> list[Meeting]:
        """Encontra reuniões que existem no banco mas não estão na interface.

        Args:
            ids_in_interface: Conjunto de IDs de reuniões atualmente
                              carregados na interface do Streamlit

        Returns:
            Lista de reuniões que estão no banco mas não na interface
        """
        logger.info(
            "[Validation Agent] Validando %d IDs da interface contra o banco...",
            len(ids_in_interface),
        )

        all_db_meetings = self._repository.list_all()
        db_ids = {m.id for m in all_db_meetings}

        missing_ids = db_ids - ids_in_interface

        if not missing_ids:
            logger.info("[Validation Agent] Nenhuma reunião faltando — banco sincronizado.")
            return []

        missing_meetings = [m for m in all_db_meetings if m.id in missing_ids]

        logger.info(
            "[Validation Agent] %d reuniões encontradas no banco mas não na interface.",
            len(missing_meetings),
        )

        return missing_meetings

    def sync_meetings_from_db(
        self,
        ids_in_interface: set[str],
    ) -> list[Meeting]:
        """Retorna todas as reuniões do banco que devem estar na interface.

        Primeiro valida se há reuniões faltando, depois retorna a lista
        completa de reuniões do banco para sincronizar a interface.

        Args:
            ids_in_interface: Conjunto de IDs na interface

        Returns:
            Lista completa de reuniões do banco (ordenadas por data)
        """
        missing = self.find_missing_meetings(ids_in_interface)
        if missing:
            logger.info(
                "[Validation Agent] Sincronizando %d reuniões para a interface...",
                len(missing),
            )

        all_meetings = self._repository.list_all()
        return all_meetings

    def validate_and_report(
        self,
        ids_in_interface: set[str],
    ) -> dict:
        """Valida e retorna um relatório completo do estado da sincronia.

        Args:
            ids_in_interface: Conjunto de IDs na interface

        Returns:
            Dicionário com:
                - synced: bool (se está tudo sincronizado)
                - total_in_db: int
                - total_in_interface: int
                - missing_count: int
                - missing_meetings: list[Meeting]
        """
        all_db = self._repository.list_all()
        db_ids = {m.id for m in all_db}

        missing_ids = db_ids - ids_in_interface
        missing = [m for m in all_db if m.id in missing_ids]

        report = {
            "synced": len(missing) == 0,
            "total_in_db": len(db_ids),
            "total_in_interface": len(ids_in_interface),
            "missing_count": len(missing),
            "missing_meetings": missing,
        }

        if report["synced"]:
            logger.info("[Validation Agent] Relatório: banco sincronizado com a interface.")
        else:
            logger.warning(
                "[Validation Agent] Relatório: %d reuniões não estão na interface.",
                len(missing),
            )

        return report

    def list_all_meetings(self) -> list[Meeting]:
        """Retorna todas as reuniões do banco.

        Útil para carregar o histórico completo na inicialização.
        """
        return self._repository.list_all()
