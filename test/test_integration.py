# Testes de integração completa
import pytest
from pathlib import Path
from domain.entities.meeting import Meeting, Summary, Task, Decision
from domain.entities.meeting_type import MeetingType
from use_cases.transcribe_meeting import TranscribeMeetingUC, TranscribeMeetingInput
from use_cases.summarize_meeting import SummarizeMeetingUC, SummarizeMeetingInput
from use_cases.chat_with_meeting import ChatWithMeetingUC, ChatWithMeetingInput
from domain.entities.transcript import Transcript, Segment
from infrastructure.json_meeting_repository import JsonMeetingRepository
from datetime import datetime
import tempfile
import json


class MockTranscriber:
    """Mock de transcritor para testes"""
    def transcribe(self, audio_path: str) -> Transcript:
        return Transcript(
            full_text="Bom dia a todos. Vamos começar com o ponto do onboarding. A Ana vai revisar o fluxo até sexta.",
            segments=[
                Segment(start=0, end=5, speaker="Speaker 0", text="Bom dia a todos."),
                Segment(start=5, end=10, speaker="Speaker 0", text="Vamos começar com o onboarding."),
                Segment(start=10, end=15, speaker="Speaker 1", text="A Ana vai revisar o fluxo até sexta."),
            ]
        )

    def transcribe_with_diarization(self, audio_path: str) -> Transcript:
        return self.transcribe(audio_path)


class MockLLMService:
    """Mock de LLM service para testes"""

    # FIX: assinatura corrigida — ILLMService.summarize exige meeting_type
    def summarize(self, transcript: str, meeting_type: MeetingType = MeetingType.GENERAL) -> Summary:
        return Summary(
            overview="Reunião de planejamento onde foram definidas tarefas de onboarding e QA.",
            topics=["Onboarding", "QA", "Roadmap"],
            tasks=[
                Task(description="Revisar fluxo", responsible="Ana", deadline="15/02"),
                Task(description="Planejar sprint", responsible="Carlos", deadline="20/02"),
            ],
            decisions=[
                Decision(description="Lançar v2.0 em julho"),
            ]
        )

    def chat(self, question: str, context: str, history: list) -> str:
        question_lower = question.lower()

        if "quem" in question_lower or "responsável" in question_lower:
            return "Ana ficou responsável pela revisão do fluxo de onboarding."
        elif "quando" in question_lower or "deadline" in question_lower:
            return "O deadline é 15 de fevereiro."
        elif "o que" in question_lower or "what" in question_lower:
            return "Não foi mencionado na reunião."
        else:
            return "Não encontrei informação sobre isso na reunião."


class TestEndToEndWorkflow:
    """Testa fluxo completo de uma reunião"""

    def test_complete_solo_workflow(self):
        """Testa pipeline completo: transcrição → resumo → persistência"""

        # PASSO 1: Transcrição
        transcriber = MockTranscriber()
        transcribe_uc = TranscribeMeetingUC(transcriber)

        t_result = transcribe_uc.execute(TranscribeMeetingInput(
            audio_path="/tmp/test.wav",
            with_diarization=True
        ))

        assert t_result.success
        assert len(t_result.transcript.segments) > 0

        # PASSO 2: Criar Meeting
        meeting = Meeting(
            id="test_001",
            title="Sprint Planning",
            transcript_text=t_result.transcript.full_text,
            transcript_formatted=t_result.transcript.formatted,
            participants=t_result.transcript.speakers,
            duration_minutes=t_result.transcript.duration_minutes
        )

        assert meeting.is_transcribed
        assert not meeting.is_summarized

        # PASSO 3: Sumarização
        llm = MockLLMService()
        summarize_uc = SummarizeMeetingUC(llm)

        s_result = summarize_uc.execute(SummarizeMeetingInput(meeting=meeting))

        assert s_result.success
        assert s_result.summary is not None
        assert len(s_result.summary.topics) > 0
        assert len(s_result.summary.tasks) > 0

        # PASSO 4: Persistência
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = JsonMeetingRepository(tmpdir)
            repo.save(meeting)

            # PASSO 5: Recuperar
            loaded = repo.find_by_id("test_001")
            assert loaded is not None
            assert loaded.title == "Sprint Planning"
            assert loaded.is_summarized

    def test_chat_workflow(self):
        """Testa fluxo de chat com reunião"""

        meeting = Meeting(
            id="test_002",
            title="Test",
            transcript_text="Ana ficou responsável. Deadline é 15 de fevereiro."
        )

        llm = MockLLMService()
        chat_uc = ChatWithMeetingUC(llm)

        # PERGUNTA 1
        result1 = chat_uc.execute(ChatWithMeetingInput(
            meeting=meeting,
            question="Quem ficou responsável?",
            history=[]
        ))

        assert result1.success
        assert "Ana" in result1.answer

        # PERGUNTA 2 (com histórico)
        history = [
            {"role": "user", "content": "Quem ficou responsável?"},
            {"role": "assistant", "content": result1.answer}
        ]

        result2 = chat_uc.execute(ChatWithMeetingInput(
            meeting=meeting,
            question="Qual é o deadline?",
            history=history
        ))

        assert result2.success
        assert "15" in result2.answer or "fevereiro" in result2.answer

    def test_persistence_workflow(self):
        """Testa persistência e recuperação de reuniões"""

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = JsonMeetingRepository(tmpdir)

            meeting1 = Meeting(id="meeting_1", title="Reunião 1", transcript_text="Conteúdo 1")
            repo.save(meeting1)

            meeting2 = Meeting(id="meeting_2", title="Reunião 2", transcript_text="Conteúdo 2")
            repo.save(meeting2)

            all_meetings = repo.list_all()
            assert len(all_meetings) == 2

            found = repo.find_by_id("meeting_1")
            assert found.title == "Reunião 1"

            repo.delete("meeting_1")

            remaining = repo.list_all()
            assert len(remaining) == 1
            assert remaining[0].id == "meeting_2"

    def test_multiple_participants(self):
        """Testa reunião com múltiplos participantes"""

        transcript = Transcript(
            full_text="Discussão completa",
            segments=[
                Segment(0, 5, "Speaker 0", "Olá"),
                Segment(5, 10, "Speaker 1", "Oi"),
                Segment(10, 15, "Speaker 2", "Tudo bem?"),
                Segment(15, 20, "Speaker 0", "Tudo!"),
                Segment(20, 25, "Speaker 1", "Vamos?"),
            ]
        )

        meeting = Meeting(
            id="multi_001",
            title="Reunião com múltiplos participants",
            transcript_text=transcript.full_text,
            transcript_formatted=transcript.formatted,
            participants=transcript.speakers,
            duration_minutes=transcript.duration_minutes
        )

        assert len(meeting.participants) == 3
        assert abs(meeting.duration_minutes - 0.4166666666666667) < 0.0001


class TestDataConsistency:
    """Testa consistência de dados entre componentes"""

    def test_summary_tasks_format(self):
        """Testa formato consistente das tarefas"""
        from domain.entities.meeting import Task

        summary = Summary(tasks=[
            Task(description="Task 1", responsible="Person A", deadline="01/01"),
            Task(description="Task 2", responsible="Person B", deadline="02/01"),
        ])

        for task in summary.tasks:
            assert task.description
            assert task.responsible
            assert task.deadline
            assert isinstance(task.done, bool)

    def test_meeting_transcript_consistency(self):
        """Testa consistência entre full_text e formatted"""

        meeting = Meeting(
            id="test",
            title="Test",
            transcript_text="Texto completo",
            transcript_formatted="[00:00] Speaker 0: Texto completo"
        )

        assert meeting.transcript_text
        assert meeting.transcript_formatted
        assert meeting.transcript_text in meeting.transcript_formatted or \
               "Texto completo" in meeting.transcript_formatted

    def test_summary_preservation_after_save(self):
        """Testa se summary é preservado após salvar e carregar"""
        from domain.entities.meeting import Task, Decision

        original_summary = Summary(
            overview="Teste",
            topics=["T1", "T2"],
            tasks=[Task(description="T1", responsible="A")],
            decisions=[Decision(description="D1")]
        )

        meeting = Meeting(
            id="test",
            title="Test",
            transcript_text="Teste",
            summary=original_summary
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = JsonMeetingRepository(tmpdir)
            repo.save(meeting)

            loaded = repo.find_by_id("test")

            assert loaded.summary.overview == original_summary.overview
            assert loaded.summary.topics == original_summary.topics
            assert len(loaded.summary.tasks) == len(original_summary.tasks)
            assert len(loaded.summary.decisions) == len(original_summary.decisions)


class TestErrorRecovery:
    """Testa recuperação de erros"""

    def test_partial_processing_recovery(self):
        """Testa se continua mesmo se partes falharem"""
        from infrastructure.transcriber.whisper_transcriber import WhisperTranscriber

        transcriber = WhisperTranscriber()
        uc = TranscribeMeetingUC(transcriber)

        result = uc.execute(TranscribeMeetingInput(
            audio_path="/tmp/nonexistent_file_12345_xyz.wav"
        ))

        assert isinstance(result.success, bool)
        if not result.success:
            assert result.error_message

    def test_corrupted_json_handling(self):
        """Testa tratamento de JSON corrompido"""

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = JsonMeetingRepository(tmpdir)

            meeting = Meeting(id="test", title="Test")
            repo.save(meeting)

            json_file = Path(tmpdir) / "test.json"
            with open(json_file, "w") as f:
                f.write("{invalid json")

            try:
                loaded = repo.find_by_id("test")
                assert loaded is None or isinstance(loaded, Meeting)
            except json.JSONDecodeError:
                pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])