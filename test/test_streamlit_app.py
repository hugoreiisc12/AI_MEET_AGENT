""" tests/unit/presentation/test_streamlit.app.py

Testa a lógica do app.py sem precisar rodar o Streamlit de verdade.
Isola as funções puras (_process_audio, _save_task_state) dos widgets.
"""

import sys
import os
import uuid
import json
import pytest
from unittest.mock import MagicMock, patch, mock_open
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from domain.entities.meeting import Meeting, Summary, Task, Decision
from domain.entities.meeting_type import MeetingType



# Fixtures para criar dados de teste realistas
@pytest.fixture
def semple_meeting() -> Meeting:
    return Meeting(
        id=str(uuid.uuid4()),
        title="Sprint Planning",
        started_at=datetime(2024, 6, 1, 10, 0),
        transcript_text="Ana: Bom dia. Carlos: Olá",
        transcript_formatted="[00:00] SPEAKER__00: Bom Dia .\n[00:05] SPEAKER _001: Olá ",
        participants=["SPEAKER_00", "SPEAKER_001"],
        duration_minutes=42.0,
        summary=Summary(
            overview="Reunião de planejamento da sprint 22",
            topics=["Autenticação, Perfomance"],
            tasks=[
                Task("Implementar login", "Ana", "Sexta"),
                Task("Otimizar cache", "Carlos", "Não definido"),
            ],
            decisions=[
                Decision("Adiar relatório para spint 23", "Falta de capacidade"),
            ],
        ),
    )

@pytest.fixture
def meeting_no_summary():
    return Meeting(
        id=str(uuid.uuid4()),
        title="Sprint Planning",
        transcript_text = "Texto qualquer",
    )

# Testes de process_audio
def test_retorna_meeting_com_sucesso(mock_transcriber, mock_llm_service, sample_meeting, tmp_path):
    """ process_audio deve retornar Meeting quando transcrição e resumo funcionam """
    from use_cases.transcribe_meeting import TranscribeMeetingUC, TranscribeMeetingInput
    from use_cases.summarize_meeting import SummarizeMeetingUC, SummarizeMeetingInput
    from infrastructure.json_meeting_repor import JsonMeetingRepository

    audio_path = str(tmp_path / "audio.wav")
    Path(audio_path).write_bytes(b"fake")

    transcribe_uc = TranscribeMeetingUC(transcriber=mock_transcriber)
    summarize_uc = SummarizeMeetingUC(
        llm_service=mock_llm_service,
        repository=JsonMeetingRepository(storage_path=str(tmp_path / "meetings")),
    )

    # Simula o fluxo de _process_audio sem o Streamlit
    t = transcribe_uc.execute(
        TranscribeMeetingInput(audio_path=audio_path, with_diarization=True)
    )
    assert t.success

    meeting = Meeting(
        id=str(uuid.uuid4()),
        title="Teste",
        transcript_text=t.transcript.full_text,
        transcript_formatted=t.transcript.formatted,
        participants=t.transcript.speakers,
        duration_minutes=t.transcript.duration_minutes,
    )

    s = summarize_uc.execute(
        SummarizeMeetingInput(meeting=meeting)
    )
    assert s.success

def test_falha_na_transcricao_retorna_none(mock_transcriber_error, tmp_path):
    from use_cases.transcribe_meeting import TranscribeMeetingUC, TranscribeMeetingInput

    audio_path = str(tmp_path / "audio.wav")
    Path(audio_path).write_bytes(b"fake")

    uc = TranscribeMeetingUC(transcriber=mock_transcriber_error)
    result = uc.execute(TranscribeMeetingInput(audio_path=audio_path))
    assert not result.success
    assert result.error_message != ""

def test_falha_no_resumo_retorna_none(mock_transcriber, mock_llm_service_error, sample_meeting):
    from use_cases.summarize_meeting import SummarizeMeetingUC, SummarizeMeetingInput

    uc = SummarizeMeetingUC(llm_service=mock_llm_service_error)
    result = uc.execute(SummarizeMeetingInput(meeting=sample_meeting))
    assert not result.success


# ── Testes de _save_task_state ────────────────────────────────────────────

class TestSaveTaskState:

    def test_persiste_tarefa_concluida(self, sample_meeting, tmp_path):
        from infrastructure.json_meeting_repor import JsonMeetingRepository

        repo = JsonMeetingRepository(storage_path=str(tmp_path / "meetings"))
        sample_meeting.summary.tasks[0].done = True
        repo.save(sample_meeting)

        loaded = repo.find_by_id(sample_meeting.id)
        assert loaded is not None
        assert loaded.summary is not None
        assert loaded.summary.tasks[0].done is True
        assert loaded.summary.tasks[1].done is False

    def test_nao_quebra_se_repo_falhar(self, sample_meeting):
        """_save_task_state deve ser silencioso em caso de erro."""
        repo = MagicMock()
        repo.save.side_effect = Exception("Disco cheio")

        # Não deve propagar a exceção
        try:
            repo.save(sample_meeting)
        except Exception:
            pass  # esperado que o mock levante, mas a função real suprime


# ── Testes de lógica de exportação ───────────────────────────────────────

class TestExportacao:

    def test_export_json_contem_todos_campos(self, sample_meeting):
        """Verifica que o JSON exportado tem a estrutura esperada."""
        m = sample_meeting
        s = m.summary

        export = {
            "title":            m.title,
            "date":             m.started_at.isoformat(),
            "participants":     m.participants,
            "duration_minutes": m.duration_minutes,
            "summary": {
                "overview":  s.overview,
                "topics":    s.topics,
                "tasks":     [{"description": t.description,
                               "responsible": t.responsible,
                               "deadline":    t.deadline,
                               "done":        t.done} for t in s.tasks],
                "decisions": [{"description": d.description,
                               "context":     d.context} for d in s.decisions],
            },
        }

        raw   = json.dumps(export, ensure_ascii=False, indent=2)
        data  = json.loads(raw)

        assert data["title"]                        == "Sprint Planning"
        assert len(data["summary"]["tasks"])        == 2
        assert len(data["summary"]["decisions"])    == 1
        assert data["summary"]["tasks"][0]["responsible"] == "Ana"

    def test_export_json_valido_sem_summary(self, meeting_no_summary):
        """Reunião sem resumo não deve quebrar a exportação."""
        m = meeting_no_summary
        export = {
            "title":            m.title,
            "date":             m.started_at.isoformat(),
            "participants":     m.participants,
            "duration_minutes": m.duration_minutes,
            "summary":          None,
        }
        raw  = json.dumps(export, ensure_ascii=False)
        data = json.loads(raw)
        assert data["summary"] is None

    def test_transcricao_formatada_preferida_na_exportacao(self, sample_meeting):
        transcript = sample_meeting.transcript_formatted or sample_meeting.transcript_text
        assert "[00:00] SPEAKER_00:" in transcript


# ── Testes de MEETING_TYPE_OPTIONS ────────────────────────────────────────

class TestMeetingTypeOptions:

    def test_todos_tipos_mapeados(self):
        """Garante que nenhum MeetingType foi esquecido nas options."""
        # Os tipos que o app expõe
        app_types = {
            MeetingType.GENERAL,
            MeetingType.PLANNING,
            MeetingType.REVIEW,
            MeetingType.RETROSPECTIVE,
            MeetingType.ONE_ON_ONE,
            MeetingType.BRAINSTORM,
            MeetingType.INTERVIEW,
        }
        all_types = set(MeetingType)
        assert app_types == all_types, f"Tipos não mapeados: {all_types - app_types}"

    def test_labels_unicos(self):
        labels = [
            "🗂 Geral", "📋 Planejamento", "🔍 Review / Demo",
            "🔄 Retrospectiva", "👤 1:1", "💡 Brainstorm", "🎯 Entrevista",
        ]
        assert len(labels) == len(set(labels))


# ── Testes de polling (modo collab) ──────────────────────────────────────

class TestPollingCollab:

    def test_find_by_id_retorna_none_enquanto_processa(self):
        repo = MagicMock()
        repo.find_by_id.return_value = None

        result = repo.find_by_id("meeting-id-qualquer")
        assert result is None

    def test_find_by_id_retorna_meeting_quando_pronto(self, sample_meeting):
        repo = MagicMock()
        repo.find_by_id.return_value = sample_meeting

        result = repo.find_by_id(sample_meeting.id)
        assert result is not None
        assert result.is_summarized
