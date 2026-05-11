# Implementação a arquitetura em camadas com injeção de dependência, 
# que ta permitinndo usar diferentes implementações do transcritor


from dataclasses import dataclass
from entities.transcript import Transcript  # CORRIGIDO: domain.entities → entities
from interface.transcriber import ITranscriber, TranscriptionError  # CORRIGIDO: domain.interfaces → interface

# Definindo os dados de entrada para transcrição
@dataclass
class TranscribeMeetingInput:
    audio_path: str
    with_diarization: bool = True
    language: str = "pt"

# Definindo os dados de saída do processo de transicrição
@dataclass
class TranscribeMeetingOutput:
    transcript: Transcript
    success: bool
    error_message: str = "PROCESS FAILED"

# Classe construtora que recebe o transcritor via injeção de dependência
class TranscribeMeetingUC:
    """
    Use case: recebe caminho de áudio, devolve transcrição.
    Não sabe qual serviço vai transcrever — recebe via injeção.
    """
# Definindo a camada de recebimento do áudio e processemanto da transcrição
    def __init__(self, transcriber: ITranscriber) -> None:
        self._transcriber = transcriber
   
# Chamada para orquestração do processo de transcição, delegando ao transcritor injetado e captura ativa de erros 
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
