# Fixture compartilhas para testes, incluinndo entidades de exemplo e mocks para interfaces 
import sys
import os
import uuid
import pytest
from datetime import datetime
from unittest.mock import MagicMock

"""
conftest.py — fixtures compartilhadas por toda a suíte de testes.

Fixtures definidas aqui ficam disponíveis automaticamente em qualquer
arquivo de teste sem precisar importar.
"""


# Garante que o root do projeto está no path
sys.path.insert(0, os.path.dirname(__file__))

from domain.entities.transcript import Transcript, Segment
from domain.entities.meeting import Meeting, Summary, Task, Decision
from domain.entities.audio_recording import AudioRecording, RecordingStatus
from domain.interfaces.transcriber import ITranscriber
from domain.interfaces.llm_service import ILLMService
from domain.interfaces.recorder import IRecorder

# Fixtures de entidades
# Criando fixtures de entidades com dados realista para testar o fluxo completo 
@pytest.fixture
def sample_segments() -> list[Segment]:
    return [
        Segment(0.0,   8.0,  "Speaker 0", "Bom dia a todos. Vamos começar com o ponto do onboarding."),
        Segment(9.5,  16.0,  "Speaker 1", "A Ana vai revisar o fluxo até sexta."),
        Segment(17.0, 24.0,  "Speaker 0", "O Carlos vai planejar o sprint de QA."),
        Segment(25.5, 32.0,  "Speaker 1", "Decidimos lançar a versão 2.0 em julho."),
    ]

# Criando fixture de Transcript que agrega os segmentos de exemplo, simulando uma reunião
@pytest.fixture
def sample_transcript(sample_segments) -> Transcript:
    full_text = " ".join(s.text for s in sample_segments)
    return Transcript(
        full_text=full_text,
        segments=sample_segments,
        language="pt",
        audio_path="tests/fixtures/sample.wav",
    )

# Fixtures de erros para testar o tratamento de exceções 
@pytest.fixture
def empty_transcript() -> Transcript:
    return Transcript(full_text="", segments=[], language="pt")

# Criando fixture de trasncrição vazia para testar cenários de erro, como transcrição falha ou aúdio sem conteúdo
@pytest.fixture
def sample_summary() -> Summary:
    return Summary(
        overview="Reunião de planejamento com definição de tarefas de onboarding e QA.",
        topics=["Revisão do fluxo de onboarding", "Planejamento sprint QA", "Lançamento v2.0"],
        tasks=[
            Task("Revisar fluxo de onboarding", "Ana", "Sexta-feira"),
            Task("Planejar sprint de QA", "Carlos", "Não definido"),
        ],
        decisions=[
            Decision("Lançar versão 2.0 em julho", "Alinhado com roadmap do produto"),
        ],
    )

# Fixtures de transcrição para testar o processo de sumarização,
#  garantindo que o resumo  gerado pela LLM seja completa 
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

# Meeting completo com transição para testar o fluxo de dados entre transcrição 
@pytest.fixture
def meeting_without_transcript() -> Meeting:
    return Meeting(
        id=str(uuid.uuid4()),
        title="Reunião sem transcrição",
    )

# Criando fixture de reunião sem trasnscrição para testar o processo de sumar 
@pytest.fixture
def sample_recording(tmp_path) -> AudioRecording:
    rec = AudioRecording(
        id=uuid.uuid4().hex,
        output_path=str(tmp_path / "recording.wav"),
    )
    rec.mark_started()
    return rec
# Fixtures de mocks (implementações fake das interfaces)
# Criando fixtures de mocks para interfaces de transcrição e LLM, 
# simulando comportamentos de sucesso e falha 
@pytest.fixture
def mock_transcriber(sample_transcript) -> ITranscriber:
    """Transcritor que sempre retorna sample_transcript."""
    transcriber = MagicMock(spec=ITranscriber)
    transcriber.transcribe.return_value = sample_transcript
    transcriber.transcribe_with_diarization.return_value = sample_transcript
    return transcriber

# Criando fixture de transcritor que sempre lança erro para testar o tratamento de exceções 
@pytest.fixture
def mock_transcriber_error() -> ITranscriber:
    """Transcritor que sempre lança erro."""
    from domain.interfaces.transcriber import TranscriptionError
    transcriber = MagicMock(spec=ITranscriber)
    transcriber.transcribe.side_effect = TranscriptionError("API indisponível")
    transcriber.transcribe_with_diarization.side_effect = TranscriptionError("API indisponível")
    return transcriber

# Criando a fixture de LLM que sempre retorna um resumo ede exemplo e respostas pré-definidas passar testar o processo
@pytest.fixture
def mock_llm_service(sample_summary) -> ILLMService:
    """LLM que sempre retorna sample_summary e responde perguntas."""
    llm = MagicMock(spec=ILLMService)
    llm.summarize.return_value = sample_summary
    llm.chat.return_value = "Ana ficou responsável pelo onboarding."
    return llm

# Criando fixture de LLm que sempre lança erro para testar o tratamento de execeções relacionados a LLM
@pytest.fixture
def mock_llm_service_error() -> ILLMService:
    """LLM que sempre lança erro."""
    from domain.interfaces.llm_service import LLMServiceError
    llm = MagicMock(spec=ILLMService)
    llm.summarize.side_effect = LLMServiceError("LLM indisponível")
    llm.chat.side_effect = LLMServiceError("LLM indisponível")
    return llm

# Criando fixture de gravador que simula gravação sem microfone para testar o processo de gravação 
@pytest.fixture
def mock_recorder() -> IRecorder:
    """Recorder que simula gravação sem microfone."""
    recorder = MagicMock(spec=IRecorder)
    recorder.is_recording.return_value = False

    _state = {"active": False, "recording": None}

    def start(output_path):
        rec = AudioRecording(id=uuid.uuid4().hex, output_path=output_path)
        rec.mark_started()
        _state["active"] = True
        _state["recording"] = rec
        recorder.is_recording.return_value = True
        return rec

    def stop():
        rec = _state["recording"]
        rec.mark_finished()
        _state["active"] = False
        recorder.is_recording.return_value = False
        return rec

    recorder.start.side_effect = start
    recorder.stop.side_effect = stop
    recorder.list_devices.return_value = [
        {"index": 0, "name": "Mock Mic", "channels": 1, "sample_rate": 16000}
    ]
    return recorder

# Criando a fixture de gravador que simula erro ao inicializar para testar o tratamento de exceções relacionadas 
@pytest.fixture
def mock_repository(sample_meeting) -> MagicMock:
    """Repositório em memória para testes."""
    from domain.repositories.meeting_repository import IMeetingRepository
    repo = MagicMock(spec=IMeetingRepository)
    _store = {}

    def save(meeting):
        _store[meeting.id] = meeting

    def find_by_id(meeting_id):
        return _store.get(meeting_id)

    def list_all():
        return sorted(_store.values(), key=lambda m: m.started_at, reverse=True)

    def delete(meeting_id):
        _store.pop(meeting_id, None)

    repo.save.side_effect = save
    repo.find_by_id.side_effect = find_by_id
    repo.list_all.side_effect = list_all
    repo.delete.side_effect = delete
    return repo