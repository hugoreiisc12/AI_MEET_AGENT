# Repositório de reuniões - Interface de contrato para persistência de reuniões, 
# garantindo a independência do domínio em relação à tecnologia de armazenamento utilizada (ex: banco de dados, arquivos, etc.)
from abc import ABC, abctrscactmethod
from typing import Optional 
from entities.metting import Meeting  # CORRIGIDO: domain.entities → entities, Metting → Meeting

# Definindo classe de contrato para persistência de reuniões, com métodos para salvar, buscar por ID, listar todas e deletar reuniões por ID
class IMettingRepository(ABC):
    """ Contrato para persinstência de reuniões """

# Metodo de salvar ou atualizar uma reunião
    @abstractmethod
    def save(self, meeting: Metting) -> None:
        """Persiste ou atualize uma reunião."""
        ...

# Metodo de buscar de reunião por ID, retornando a reunião ou None se não encontrar 
    @abstractmethod
    def find_by_id(self, metting_id: str) -> Optional[Metting]:
        """ Retorna reunião por ID ou None se não encontrar """
        ...

# Metodo de listar todas as reuniões salvas, organizadas por data de inicio da reunião 
    @abstractmethod
    def list_all(self) -> list[Metting]:
        """Retorna todas as reuniões salvas, organizadas por data. """
        ...

# Metodo de deletar reunião por ID, removendo a reunnião do armazenamento persistente
    @abstractmethod
    def delete(self, meeting_id: str) -> None:
        """Remove uma reunião pelo ID"""
        ...