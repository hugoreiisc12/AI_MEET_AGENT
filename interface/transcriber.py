# Interface transcritor que define o contrato para qualquer implementação de transcrição
from abc import ABC, abstractmethod
from entities.transcript import Transcript


# Classe abstrata que qualquer transcritor deve implementar
class ITranscriber(ABC):
    """Contrato que qualquer implementação de transcrição deve seguir."""

    # Transcreve arquivo de áudio retornando Transcript
    @abstractmethod
    def transcribe(self, audio_path: str) -> Transcript:
        """Transcreve arquivo retornando Transcript com texto e metadados."""
        ...

    # Transcreve e identifica speakers (diarização)
    @abstractmethod
    def transcribe_with_diarization(self, audio_path: str) -> Transcript:
        """Transcreve identificando speakers e timestamps de cada segmento."""
        ...


# Exceção específica para erros durante transcrição
class TranscriptionError(Exception):
    """Erro durante processo de transcrição."""
    pass
