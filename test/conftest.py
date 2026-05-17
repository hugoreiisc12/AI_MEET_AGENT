"""
conftest.py — fixtures compartilhadas por toda a suíte de testes.
"""
import sys
import os
import uuid
import pytest
from datetime import datetime
from unittest.mock import MagicMock

# Garante que o ROOT do projeto está no path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from entities.transcript import Transcript, Segment
from entities.metting import Meeting, Summary, Task, Decision
from interface.transcriber import ITranscriber, TranscriptionError
from interface.llm_services import ILLMService, LLMServiceError
from repositores.metting_repor import IMeetingRepository


@pytest.fixture
def sample_segments() -> list[Segment]:
    return [
        Segment(0.0,   8.0,  "Speaker 0", "Bom dia a todos. Vamos começar com o ponto do onboarding."),
        Segment(9.5,  16.0,  "Speaker 1", "A Ana vai revisar o fluxo até sexta."),
        Segment(17.0, 24.0,  "Speaker 0", "O Carlos vai planejar o sprint de QA."),
        Segment(25.5, 32.0,  "Speaker 1", "Decidimos lançar a versão 2.0 em julho."),
    ]


@pytest.fixture
def sample_transcript(sample_segments) -> Transcript:
    full_text = " ".join(s.text for s in sample_segments)
    return Transcript(
        full_text=full_text,
        segments=sample_segments,
        language="pt",
        audio_path="tests/fixtures/sample.wav",
    )


@pytest.fixture
def empty_transcript() -> Transcript:
    return Transcript(full_text="", segments=[], language="pt")


@pytest.fixture
def sample_summary() -> Summary:
    return Summary(
        overview="Reunião de planejamento com definição de tarefas de onboarding e QA.",
        topics=["Revisão do fluxo de onboarding", "Planejamento sprint QA", "Lançamento v2.0"],
        tasks=[
            Task("Revisar fluxo de onboarding", "Ana", "Sexta-feira"),
            Task("Planejar sprint de QA", "Carlos", None),
        ],
        decisions=[
            Decision("Lançar versão 2.0 em julho", "Alinhado com roadmap do produto"),
        ],
    )


@pytest.fixture
def sample_meeting(sample_transcript, sample_summary) -> Meeting:
    return Meeting(
        id=str(uuid.uuid4()),
        title="Sprint Planning — Semana 22",
        started_at=datetime(2024, 5, 20, 10, 0, 0),
        audio_path="tests/fixtures/sample.wav",
        transcript_text=sample_transcript.full_text,
        transcript_formatted=sample_transcript.formatted,
        participants=sample_transcript.speakers,
        duration_minutes=sample_transcript.duration_minutes,
        summary=sample_summary,
    )


@pytest.fixture
def meeting_without_transcript() -> Meeting:
    return Meeting(
        id=str(uuid.uuid4()),
        title="Reunião sem transcrição",
    )


@pytest.fixture
def mock_transcriber(sample_transcript) -> ITranscriber:
    """Transcritor que sempre retorna sample_transcript."""
    transcriber = MagicMock(spec=ITranscriber)
    transcriber.transcribe.return_value = sample_transcript
    transcriber.transcribe_with_diarization.return_value = sample_transcript
    return transcriber


@pytest.fixture
def mock_transcriber_error() -> ITranscriber:
    """Transcritor que sempre lança erro."""
    transcriber = MagicMock(spec=ITranscriber)
    transcriber.transcribe.side_effect = TranscriptionError("API indisponível")
    transcriber.transcribe_with_diarization.side_effect = TranscriptionError("API indisponível")
    return transcriber


@pytest.fixture
def mock_llm_service(sample_summary) -> ILLMService:
    """LLM que sempre retorna sample_summary e responde perguntas."""
    llm = MagicMock(spec=ILLMService)
    llm.summarize.return_value = sample_summary
    llm.chat.return_value = "Ana ficou responsável pelo onboarding."
    return llm


@pytest.fixture
def mock_llm_service_error() -> ILLMService:
    """LLM que sempre lança erro."""
    llm = MagicMock(spec=ILLMService)
    llm.summarize.side_effect = LLMServiceError("LLM indisponível")
    llm.chat.side_effect = LLMServiceError("LLM indisponível")
    return llm


@pytest.fixture
def mock_repository(sample_meeting) -> MagicMock:
    """Repositório em memória para testes."""
    repo = MagicMock(spec=IMeetingRepository)
    _store = {sample_meeting.id: sample_meeting}

    repo.save.side_effect = lambda m: _store.update({m.id: m})
    repo.find_by_id.side_effect = lambda mid: _store.get(mid)
    repo.list_all.side_effect = lambda: sorted(_store.values(), key=lambda m: m.started_at, reverse=True)
    repo.delete.side_effect = lambda mid: _store.pop(mid, None)
    return repo