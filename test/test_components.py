# Testes de componentes individuais
import pytest
from domain.entities.meeting import Meeting, Summary, Task, Decision
from datetime import datetime


class TestMeetingEntity:
    """Testa entidade Meeting"""
    
    def test_meeting_creation(self):
        """Testa se Meeting pode ser criada"""
        meeting = Meeting(
            id="123",
            title="Sprint Planning",
            started_at=datetime.now(),
            audio_path="/tmp/audio.wav"
        )
        assert meeting.id == "123"
        assert meeting.title == "Sprint Planning"
        assert meeting.is_transcribed == False  # Sem transcrição ainda
    
    def test_meeting_transcribed_status(self):
        """Testa property is_transcribed"""
        meeting = Meeting(id="123", title="Test")
        assert meeting.is_transcribed == False
        
        meeting.transcript_text = "Bom dia a todos"
        assert meeting.is_transcribed == True
    
    def test_meeting_summarized_status(self):
        """Testa property is_summarized"""
        meeting = Meeting(id="123", title="Test")
        assert meeting.is_summarized == False
        
        meeting.summary = Summary(overview="Reunião de teste")
        assert meeting.is_summarized == True


class TestSummaryEntity:
    """Testa entidade Summary"""
    
    def test_summary_creation(self):
        """Testa se Summary pode ser criada"""
        summary = Summary(
            overview="Reunião de planejamento",
            topics=["Onboarding", "QA"],
            tasks=[Task(description="Revisar")],
            decisions=[Decision(description="Lançar v2.0")]
        )
        assert summary.overview == "Reunião de planejamento"
        assert len(summary.topics) == 2
        assert len(summary.tasks) == 1
        assert len(summary.decisions) == 1
    
    def test_summary_has_tasks(self):
        """Testa property has_tasks"""
        summary = Summary()
        assert summary.has_tasks == False
        
        summary.tasks = [Task(description="Tarefa 1")]
        assert summary.has_tasks == True
    
    def test_summary_pending_tasks(self):
        """Testa filtragem de tarefas pendentes"""
        summary = Summary(tasks=[
            Task(description="Tarefa 1", done=False),
            Task(description="Tarefa 2", done=True),
            Task(description="Tarefa 3", done=False),
        ])
        
        pending = summary.pending_tasks
        assert len(pending) == 2
        assert all(not t.done for t in pending)
    
    def test_summary_formatted_output(self):
        """Testa formatação visual do summary"""
        summary = Summary(
            overview="Teste",
            topics=["Topic 1"],
            tasks=[Task(description="Task 1")],
            decisions=[Decision(description="Decision 1")]
        )
        
        formatted = summary.formatted
        assert "Visão Geral" in formatted
        assert "Tópicos Discutidos" in formatted
        assert "Tarefas" in formatted
        assert "Decisões Tomadas" in formatted


class TestTaskEntity:
    """Testa entidade Task"""
    
    def test_task_creation(self):
        """Testa criação de Task"""
        task = Task(
            description="Revisar fluxo",
            responsible="Ana",
            deadline="15/02/2024"
        )
        assert task.description == "Revisar fluxo"
        assert task.responsible == "Ana"
        assert task.done == False
    
    def test_task_str_format(self):
        """Testa formatação visual da task"""
        task = Task(
            description="Revisar",
            responsible="Ana",
            deadline="15/02"
        )
        
        formatted = str(task)
        assert "Revisar" in formatted
        assert "Ana" in formatted
        assert "15/02" in formatted
        assert "⬜" in formatted  # Task não feita
    
    def test_task_done_status(self):
        """Testa indicador visual de conclusão"""
        task_pending = Task(description="Test", done=False)
        task_done = Task(description="Test", done=True)
        
        assert "⬜" in str(task_pending)  # Não concluída
        assert "✅" in str(task_done)     # Concluída


class TestDecisionEntity:
    """Testa entidade Decision"""
    
    def test_decision_creation(self):
        """Testa criação de Decision"""
        decision = Decision(
            description="Lançar v2.0 em julho",
            context="Alinhamento com roadmap"
        )
        assert decision.description == "Lançar v2.0 em julho"
        assert decision.context == "Alinhamento com roadmap"
    
    def test_decision_str_format(self):
        """Testa formatação visual da decision"""
        decision = Decision(description="Lançar v2.0")
        formatted = str(decision)
        
        assert "•" in formatted  # Prefixo
        assert "Lançar v2.0" in formatted


class TestTranscriptEntity:
    """Testa entidade Transcript"""
    
    def test_transcript_creation(self):
        """Testa criação de Transcript"""
        from domain.entities.transcript import Transcript, Segment
        
        transcript = Transcript(
            full_text="Bom dia a todos",
            segments=[
                Segment(start=0, end=5, speaker="Speaker 0", text="Bom dia")
            ]
        )
        
        assert transcript.full_text == "Bom dia a todos"
        assert len(transcript.segments) == 1
    
    def test_transcript_has_diarization(self):
        """Testa property has_diarization"""
        from domain.entities.transcript import Transcript
        
        t1 = Transcript(full_text="Test")
        assert t1.has_diarization == False
        
        t2 = Transcript(full_text="Test", segments=[])
        assert t2.has_diarization == False
    
    def test_transcript_duration(self):
        """Testa cálculo de duração"""
        from domain.entities.transcript import Transcript, Segment
        
        transcript = Transcript(
            full_text="Test",
            segments=[
                Segment(start=0, end=30, speaker="S0", text="Início"),
                Segment(start=30, end=120, speaker="S0", text="Fim"),
            ]
        )
        
        duration = transcript.duration_minutes
        assert duration == 2.0  # 120 segundos = 2 minutos
    
    def test_transcript_speakers(self):
        """Testa extração de speakers únicos"""
        from domain.entities.transcript import Transcript, Segment
        
        transcript = Transcript(
            full_text="Test",
            segments=[
                Segment(start=0, end=10, speaker="Speaker 0", text="Olá"),
                Segment(start=10, end=20, speaker="Speaker 1", text="Oi"),
                Segment(start=20, end=30, speaker="Speaker 0", text="Tudo bem?"),
            ]
        )
        
        speakers = transcript.speakers
        assert len(speakers) == 2
        assert "Speaker 0" in speakers
        assert "Speaker 1" in speakers


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
