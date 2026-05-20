# Testes de performance e latência
import pytest
import time
from use_cases.transcribe_meeting import TranscribeMeetingUC, TranscribeMeetingInput
from use_cases.summarize_meeting import SummarizeMeetingUC, SummarizeMeetingInput
from use_cases.chat_with_meeting import ChatWithMeetingUC, ChatWithMeetingInput
from domain.entities.meeting import Meeting, Summary, Task, Decision
from domain.entities.transcript import Transcript, Segment
from datetime import datetime


class MockTranscriberFast:
    """Transcritor mock muito rápido"""
    def transcribe(self, audio_path: str) -> Transcript:
        return Transcript(full_text="Transcrição rápida")

    def transcribe_with_diarization(self, audio_path: str) -> Transcript:
        return Transcript(
            full_text="Transcrição com speakers",
            segments=[
                Segment(start=0, end=10, speaker="Speaker 0", text="Oi"),
                Segment(start=10, end=20, speaker="Speaker 1", text="Olá"),
            ]
        )


class MockLLMServiceFast:
    """LLM mock rápido"""
    def summarize(self, transcript: str) -> Summary:
        return Summary(
            overview="Resumo rápido",
            topics=["Topic 1", "Topic 2"],
            tasks=[Task(description="Task 1")],
            decisions=[Decision(description="Decision 1")]
        )

    def chat(self, question: str, context: str, history: list) -> str:
        return "Resposta rápida"


class TestPerformance:
    """Testa performance/latência dos componentes"""

    def test_transcribe_performance(self):
        """Testa se transcrição é rápida"""
        transcriber = MockTranscriberFast()
        uc = TranscribeMeetingUC(transcriber)

        start = time.time()
        result = uc.execute(TranscribeMeetingInput(
            audio_path="/tmp/test.wav"
        ))
        elapsed = time.time() - start

        # Mock deve ser muito rápido (< 0.1 segundo)
        assert elapsed < 0.1, f"Transcrição demorou {elapsed:.3f}s"
        assert result.success

    def test_summarize_performance(self):
        """Testa se sumarização é rápida"""
        llm = MockLLMServiceFast()
        uc = SummarizeMeetingUC(llm)

        meeting = Meeting(
            id="123",
            title="Test",
            transcript_text="Transcrição de teste"
        )

        start = time.time()
        result = uc.execute(SummarizeMeetingInput(meeting=meeting))
        elapsed = time.time() - start

        # Mock deve ser muito rápido (< 0.1 segundo)
        assert elapsed < 0.1, f"Sumarização demorou {elapsed:.3f}s"
        assert result.success

    def test_chat_performance(self):
        """Testa se chat responde rápido"""
        llm = MockLLMServiceFast()
        uc = ChatWithMeetingUC(llm)

        meeting = Meeting(
            id="123",
            title="Test",
            transcript_text="Transcrição de teste"
        )

        start = time.time()
        result = uc.execute(ChatWithMeetingInput(
            meeting=meeting,
            question="Teste?",
            history=[]
        ))
        elapsed = time.time() - start

        # Mock deve ser muito rápido (< 0.1 segundo)
        assert elapsed < 0.1, f"Chat demorou {elapsed:.3f}s"
        assert result.success

    def test_batch_processing_performance(self):
        """Testa performance ao processar múltiplas reuniões"""
        transcriber = MockTranscriberFast()
        llm = MockLLMServiceFast()

        transcribe_uc = TranscribeMeetingUC(transcriber)
        summarize_uc = SummarizeMeetingUC(llm)

        start = time.time()

        # Processa 5 reuniões
        for i in range(5):
            t_result = transcribe_uc.execute(TranscribeMeetingInput(
                audio_path=f"/tmp/test{i}.wav"
            ))

            meeting = Meeting(
                id=f"test_{i}",
                title=f"Meeting {i}",
                transcript_text=t_result.transcript.full_text
            )

            summarize_uc.execute(SummarizeMeetingInput(meeting=meeting))

        elapsed = time.time() - start

        # 5 reuniões em menos de 0.5 segundo
        assert elapsed < 0.5, f"Batch demorou {elapsed:.3f}s"

    def test_memory_usage(self):
        """Testa se não usa muita memória"""
        import sys

        meeting = Meeting(
            id="123",
            title="Test",
            transcript_text="x" * 1000000  # 1MB de transcrição
        )

        summary = Summary(
            overview="y" * 100000,  # 100KB
            topics=["Topic"] * 1000,
            tasks=[Task(description=f"Task {i}") for i in range(1000)],
            decisions=[Decision(description=f"Decision {i}") for i in range(100)]
        )

        # Não deve ocupar mais que 50MB
        size = sys.getsizeof(meeting) + sys.getsizeof(summary)
        assert size < 50_000_000


class TestErrorHandling:
    """Testa tratamento de erros"""

    def test_invalid_audio_path(self):
        """Testa erro com caminho de áudio inválido"""
        from infrastructure.transcriber.whisper_transcriber import WhisperTranscriber
        from interface.transcriber import TranscriptionError

        transcriber = WhisperTranscriber()
        uc = TranscribeMeetingUC(transcriber)

        result = uc.execute(TranscribeMeetingInput(
            audio_path="/tmp/nao_existe_12345.wav"
        ))

        # Deve ter error_message preenchido
        assert result.success == False
        assert "não encontrado" in result.error_message.lower()

    def test_empty_transcript_validation(self):
        """Testa validação de transcrição vazia"""
        llm = MockLLMServiceFast()
        uc = SummarizeMeetingUC(llm)

        meeting = Meeting(
            id="123",
            title="Test",
            transcript_text=""  # Vazio!
        )

        result = uc.execute(SummarizeMeetingInput(meeting=meeting))

        # Deve falhar pois não há transcrição
        assert result.success == False

    def test_none_meeting_input(self):
        """Testa validação de entrada None"""
        llm = MockLLMServiceFast()
        uc = SummarizeMeetingUC(llm)

        # Não passa meeting
        try:
            result = uc.execute(SummarizeMeetingInput(meeting=None))
            assert False, "Deveria ter lançado erro"
        except (TypeError, AttributeError):
            # Comportamento esperado
            pass

    def test_chat_without_transcript(self):
        """Testa chat sem transcrição"""
        llm = MockLLMServiceFast()
        uc = ChatWithMeetingUC(llm)

        meeting = Meeting(
            id="123",
            title="Test",
            transcript_text=""  # Sem transcrição
        )

        result = uc.execute(ChatWithMeetingInput(
            meeting=meeting,
            question="Teste?",
            history=[]
        ))

        # Deve falhar
        assert result.success == False

    def test_invalid_meeting_data(self):
        """Testa com dados de reunião inválidos"""
        from use_cases.summarize_meeting import SummarizeMeetingInput

        llm = MockLLMServiceFast()
        uc = SummarizeMeetingUC(llm)

        # Meeting com dados incompletos
        meeting = Meeting(id=None, title="")  # Inválido

        try:
            result = uc.execute(SummarizeMeetingInput(meeting=meeting))
            # Se não lançar erro, pelo menos deve reportar falha
            if result.success:
                assert result.error_message != ""
        except (TypeError, ValueError):
            # Erro esperado
            pass


class TestInputValidation:
    """Testa validação de entradas"""

    def test_title_too_long(self):
        """Testa se aceita títulos muito longos"""
        title = "x" * 10000  # Título gigante

        meeting = Meeting(
            id="123",
            title=title,
            transcript_text="Test"
        )

        # Deve aceitar (mesmo que seja impraticável)
        assert len(meeting.title) == 10000

    def test_special_characters_in_title(self):
        """Testa caracteres especiais no título"""
        title = "Reunião 👨‍💼 <>&\"'`"

        meeting = Meeting(
            id="123",
            title=title
        )

        assert meeting.title == title

    def test_empty_summary_fields(self):
        """Testa summary com campos vazios"""
        summary = Summary(
            overview="",
            topics=[],
            tasks=[],
            decisions=[]
        )

        assert summary.has_tasks == False
        assert len(summary.pending_tasks) == 0

    def test_duplicate_topics(self):
        """Testa se aceita tópicos duplicados"""
        summary = Summary(
            topics=["Topic 1", "Topic 1", "Topic 2", "Topic 1"]
        )

        # Deve aceitar (mesmo que seja redundante)
        assert len(summary.topics) == 4


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
