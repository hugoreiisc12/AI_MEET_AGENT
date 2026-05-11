# Interface transcritor que define o contrato para qualquer implementação de transcrição
from abc import ABC, abstractmethod
from entities.transcript import Transcript  # CORRIGIDO: domain.entities → entities


# Definindo a classe abstrata que qualquer transcritor deve implementar
class ITranscriber(ABC):
    """
    Contrato que qualquer implementação de transcrição deve seguir.
    O domain não sabe (nem precisa saber) se é Whisper, Deepgram ou outro.
    """

    @abstractmethod
    def transcribe(self, audio_path: str) -> Transcript:
        """
        Transcreve um arquivo de áudio.

        Args:
            audio_path: Caminho absoluto para o arquivo .wav / .mp3 / .webm

        Returns:
            Transcript com full_text e, se disponível, segments com diarização.

        Raises:
            FileNotFoundError: se o arquivo não existir
            TranscriptionError: se a API falhar
        """
        ...

    @abstractmethod
    def transcribe_with_diarization(self, audio_path: str) -> Transcript:
        """
        Transcreve identificando quem falou cada parte.
        Implementações que não suportam diarização devem retornar
        Transcript sem segments (graceful degradation).
        """
        ...

# Definindo classe de erro específica para falhas no processo de transcrição
class TranscriptionError(Exception):
    """Erro durante processo de transcrição."""
    pass
