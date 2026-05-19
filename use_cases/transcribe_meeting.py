# Use case: orquestra transcrição de áudio com injeção de dependência
from dataclasses import dataclass
from entities.transcript import Transcript
from interface.transcriber import ITranscriber, TranscriptionError


# Dados de entrada para o processo de transcrição
@dataclass
class TranscribeMeetingInput:
    audio_path: str  # Caminho do arquivo de áudio
    with_diarization: bool = True  # Identificar speakers
    language: str = "pt"  # Idioma do áudio


# Dados de saída do processo de transcrição
@dataclass
class TranscribeMeetingOutput:
    transcript: Transcript  # Transcrição processada
    success: bool  # Status da operação
    error_message: str = ""


# Use case que recebe transcritor via injeção de dependência
class TranscribeMeetingUC:
    """Orquestra transcrição de áudio via transcritor injetado."""

    def __init__(self, transcriber: ITranscriber) -> None:
        self._transcriber = transcriber

    # Executa transcrição delegando ao serviço injetado
    def execute(self, input_data: TranscribeMeetingInput) -> TranscribeMeetingOutput:
        try:
            if input_data.with_diarization:
                transcript = self._transcriber.transcribe_with_diarization(
                    input_data.audio_path
                )
            else:
                transcript = self._transcriber.transcribe(input_data.audio_path)

            return TranscribeMeetingOutput(transcript=transcript, success=True)

        except FileNotFoundError:
            return TranscribeMeetingOutput(
                transcript=Transcript(full_text=""),
                success=False,
                error_message=f"Arquivo não encontrado: {input_data.audio_path}",
            )
        except TranscriptionError as e:
            return TranscribeMeetingOutput(
                transcript=Transcript(full_text=""),
                success=False,
                error_message=f"Erro na transcrição: {str(e)}",
            )
