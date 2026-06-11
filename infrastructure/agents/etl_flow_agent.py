import logging
import time
import uuid
from pathlib import Path
from typing import Optional, Callable

from domain.entities.meeting import Meeting
from domain.entities.transcript import Transcript
from interface.transcriber import ITranscriber
from repositories.meeting_repository import IMeetingRepository

logger = logging.getLogger(__name__)


class ETLFlowAgent:
    """Agente interno de fluxo ETL do áudio.

    Responsável por garantir que assim que o arquivo de áudio .webm é criado,
    ele seja enviado diretamente para o WhisperLocal para ser transcrito.
    Depois de transcrito, o resultado é salvo com um ID identificador
    e armazenado no banco de dados.

    Fluxo:
        1. Detecta/recebe novo arquivo .webm
        2. Envia para ITranscriber.transcribe() ou transcribe_with_diarization()
        3. Obtém o Transcript resultante
        4. Gera um ID único (UUID) para a transcrição
        5. Persiste o Meeting no IMeetingRepository
    """

    def __init__(
        self,
        transcriber: ITranscriber,
        repository: IMeetingRepository,
    ) -> None:
        self._transcriber = transcriber
        self._repository = repository

    def process_audio(
        self,
        audio_path: str,
        title: str = "Reunião",
        with_diarization: bool = True,
        language: str = "pt",
    ) -> Meeting:
        """Processa um arquivo de áudio do início ao fim do ETL.

        Args:
            audio_path: Caminho para o arquivo .webm
            title: Título da reunião
            with_diarization: Se deve aplicar pseudo-diarização
            language: Idioma do áudio

        Returns:
            Meeting com transcrição salva no banco

        Raises:
            FileNotFoundError: Se o áudio não existir
            TranscriptionError: Se a transcrição falhar
        """
        path = Path(audio_path)
        if not path.exists():
            raise FileNotFoundError(f"Áudio não encontrado: {audio_path}")

        logger.info("[ETL Agent] Iniciando ETL para: %s", audio_path)

        meeting_id = str(uuid.uuid4())

        meeting = Meeting(
            id=meeting_id,
            title=title,
            audio_path=audio_path,
        )

        self._repository.save(meeting)
        logger.info("[ETL Agent] Meeting criada com ID: %s", meeting_id)

        transcript = self._transcribe(audio_path, with_diarization, language)
        meeting.transcript_text = transcript.full_text
        meeting.transcript_formatted = transcript.formatted
        meeting.participants = transcript.speakers

        self._repository.save(meeting)
        logger.info("[ETL Agent] ETL concluído para: %s — %s", meeting_id, audio_path)

        return meeting

    def _transcribe(
        self,
        audio_path: str,
        with_diarization: bool,
        language: str,
    ) -> Transcript:
        if with_diarization:
            return self._transcriber.transcribe_with_diarization(audio_path)
        return self._transcriber.transcribe(audio_path)

    def watch_and_process(
        self,
        directory: str,
        title_callback: Optional[Callable[[str], str]] = None,
        poll_interval: float = 5.0,
        with_diarization: bool = True,
        language: str = "pt",
    ) -> None:
        """Monitora um diretório por novos arquivos .webm e processa
        automaticamente quando encontrados.

        Args:
            directory: Diretório a ser monitorado
            title_callback: Função para extrair título do nome do arquivo
            poll_interval: Intervalo entre verificações (segundos)
            with_diarization: Se deve aplicar pseudo-diarização
            language: Idioma do áudio
        """
        watch_dir = Path(directory)
        watch_dir.mkdir(parents=True, exist_ok=True)
        processed: set[str] = set()

        logger.info("[ETL Agent] Monitorando %s por novos áudios...", directory)

        while True:
            for f in watch_dir.glob("*.webm"):
                audio_path = str(f.resolve())
                if audio_path not in processed:
                    processed.add(audio_path)
                    title = title_callback(f.name) if title_callback else f.stem
                    try:
                        self.process_audio(
                            audio_path=audio_path,
                            title=title,
                            with_diarization=with_diarization,
                            language=language,
                        )
                    except Exception as e:
                        logger.exception(
                            "[ETL Agent] Erro ao processar %s: %s", audio_path, e
                        )
            time.sleep(poll_interval)
