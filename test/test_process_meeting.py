"""Pipeline único (ADR-001) e persistência de status (ADR-002)."""
from datetime import datetime

import pytest

from domain.entities.meeting import Decision, Meeting, MeetingStatus, Summary, Task
from domain.entities.transcript import Segment, Transcript
from domain.interfaces.llm_service import LLMServiceError
from domain.interfaces.transcriber import TranscriptionError
from infrastructure.json_meeting_repository import JsonMeetingRepository
from infrastructure.meeting_serialization import meeting_from_dict, meeting_to_dict
from use_cases.process_meeting import ProcessMeetingInput, ProcessMeetingUC
from use_cases.summarize_meeting import SummarizeMeetingUC
from use_cases.transcribe_meeting import TranscribeMeetingUC


class FakeTranscriber:
    def __init__(self, error=None, text="Olá, reunião de teste."):
        self.error, self.text = error, text

    def transcribe_with_diarization(self, audio_path):
        if self.error:
            raise self.error
        return Transcript(full_text=self.text, segments=[Segment(0, 60, "Speaker 0", self.text)])

    transcribe = transcribe_with_diarization


class FakeLLM:
    def __init__(self, error=None):
        self.error = error

    def summarize(self, transcript, meeting_type=None):
        if self.error:
            raise self.error
        return Summary(overview="resumo", tasks=[Task("fazer x")], decisions=[Decision("decidido y")])


@pytest.fixture
def repo(tmp_path):
    return JsonMeetingRepository(str(tmp_path / "meetings"))


@pytest.fixture
def audio(tmp_path):
    path = tmp_path / "a.webm"
    path.write_bytes(b"audio")
    return str(path)


def _uc(repo, transcriber=None, llm=None):
    return ProcessMeetingUC(
        TranscribeMeetingUC(transcriber or FakeTranscriber()),
        SummarizeMeetingUC(llm or FakeLLM()),
        repo,
    )


def test_sucesso_persiste_done_com_transcricao_e_resumo(repo, audio):
    _uc(repo).execute(ProcessMeetingInput("m1", audio, "Título"))
    saved = repo.find_by_id("m1")
    assert saved.status == MeetingStatus.DONE and saved.error == ""
    assert saved.transcript_text and saved.summary.tasks[0].description == "fazer x"
    assert saved.duration_minutes == 1.0


def test_audio_ausente_vira_erro_persistido(repo, tmp_path):
    _uc(repo).execute(ProcessMeetingInput("m1", str(tmp_path / "nao_existe.webm"), "T"))
    saved = repo.find_by_id("m1")
    assert saved.status == MeetingStatus.ERROR and "Áudio" in saved.error


def test_falha_de_transcricao_vira_erro_persistido(repo, audio):
    _uc(repo, transcriber=FakeTranscriber(error=TranscriptionError("boom"))).execute(
        ProcessMeetingInput("m1", audio, "T"))
    saved = repo.find_by_id("m1")
    assert saved.status == MeetingStatus.ERROR and "boom" in saved.error


def test_transcricao_vazia_vira_erro(repo, audio):
    _uc(repo, transcriber=FakeTranscriber(text="  ")).execute(ProcessMeetingInput("m1", audio, "T"))
    assert repo.find_by_id("m1").status == MeetingStatus.ERROR


def test_falha_do_llm_mantem_transcricao_e_marca_erro(repo, audio):
    _uc(repo, llm=FakeLLM(error=LLMServiceError("sem contexto"))).execute(
        ProcessMeetingInput("m1", audio, "T"))
    saved = repo.find_by_id("m1")
    assert saved.status == MeetingStatus.ERROR and "sem contexto" in saved.error
    assert saved.transcript_text


def test_excecao_inesperada_nao_deixa_status_preso(repo, audio):
    _uc(repo, llm=FakeLLM(error=RuntimeError("rede caiu"))).execute(ProcessMeetingInput("m1", audio, "T"))
    saved = repo.find_by_id("m1")
    assert saved.status == MeetingStatus.ERROR and "rede caiu" in saved.error


def test_reprocessar_mesmo_id_nao_duplica_e_limpa_erro(repo, audio):
    _uc(repo, transcriber=FakeTranscriber(error=TranscriptionError("boom"))).execute(
        ProcessMeetingInput("m1", audio, "T"))
    _uc(repo).execute(ProcessMeetingInput("m1", audio, "T"))
    assert len(repo.list_all()) == 1
    assert repo.find_by_id("m1").status == MeetingStatus.DONE


def test_serializacao_ida_e_volta_sem_perda():
    m = Meeting(
        id="x", title="t", started_at=datetime(2026, 11, 14, 10, 0), audio_path="a.webm",
        transcript_text="tt", transcript_formatted="tf", transcript_raw="tr",
        summary=Summary(overview="o", topics=["a"], tasks=[Task("d", "r", "amanhã", True)],
                        decisions=[Decision("d", "c")], created_at=datetime(2026, 11, 14, 11, 0)),
        participants=["A", "B"], duration_minutes=5.5, status=MeetingStatus.SUMMARIZING, error="e",
    )
    assert meeting_from_dict(meeting_to_dict(m)) == m


def test_documento_antigo_sem_status_e_derivado():
    base = {"_id": "x", "title": "t", "started_at": "2026-06-01T10:00:00"}
    assert meeting_from_dict(base).status == MeetingStatus.PENDING
    assert meeting_from_dict({**base, "summary": {"overview": "o"}}).status == MeetingStatus.DONE
    assert meeting_from_dict({**base, "status": "fallback_legendas"}).status == MeetingStatus.PENDING


def test_reuniao_pronta_vai_para_a_memoria_e_falha_dela_nao_derruba(repo, audio):
    indexed = []

    class Indexer:
        def index(self, meeting):
            indexed.append((meeting.id, meeting.status))
    uc = ProcessMeetingUC(TranscribeMeetingUC(FakeTranscriber()), SummarizeMeetingUC(FakeLLM()), repo, indexer=Indexer())
    uc.execute(ProcessMeetingInput("m1", audio, "T"))
    assert indexed == [("m1", MeetingStatus.DONE)]

    from use_cases.meeting_index import MemoryIndexer

    class Broken:
        model_name = "x"

        def embed_documents(self, texts):
            raise RuntimeError("sem modelo")
    from infrastructure.index_store import IndexStore
    uc = ProcessMeetingUC(TranscribeMeetingUC(FakeTranscriber()), SummarizeMeetingUC(FakeLLM()), repo,
                          indexer=MemoryIndexer(IndexStore(str(repo._base.parent / "index")), Broken()))
    assert uc.execute(ProcessMeetingInput("m2", audio, "T")).status == MeetingStatus.DONE
