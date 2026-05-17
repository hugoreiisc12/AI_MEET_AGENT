from dataclasses import dataclass
from entities.metting import Meeting
from entities.sentiment_result import SentimentResult
from llm.langchain_llm_service import LLMServiceError
from sentiment_analyze import SentimentAnalyzer


@dataclass
class AnalyzeSentimentInput:
    meeting: Meeting


@dataclass
class AnalyzeSentimentOutput:
    result: SentimentResult | None
    success: bool
    error_message: str = ""


class AnalyzeSentimentUC:
    """
    Use case: analisa sentimento e engajamento de uma reunião já transcrita.
    Não modifica a Meeting — retorna resultado separado.
    """

    def __init__(self, analyzer: SentimentAnalyzer) -> None:
        self._analyzer = analyzer

    def execute(self, input_data: AnalyzeSentimentInput) -> AnalyzeSentimentOutput:
        meeting = input_data.meeting

        if not meeting.is_transcribed:
            return AnalyzeSentimentOutput(
                result=None,
                success=False,
                error_message="Reunião não transcrita. Execute TranscribeMeetingUC primeiro.",
            )

        try:
            transcript = meeting.transcript_formatted or meeting.transcript_text
            result = self._analyzer.analyze(transcript)
            return AnalyzeSentimentOutput(result=result, success=True)

        except LLMServiceError as e:
            return AnalyzeSentimentOutput(
                result=None,
                success=False,
                error_message=str(e),
            )