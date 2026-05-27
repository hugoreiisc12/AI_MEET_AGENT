# Testa o fluxo completo do Meet Agent usando mocks para transcrição e LLM, sem gastar API calls
import sys
import os
import uuid
from datetime import datetime
import pytest

# Adiciona o diretório raiz ao path para permitir imports relativos
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# CORRIGIDO: Imports ajustados para a estrutura real do projeto
from domain.entities.meeting import Meeting, Summary, Task, Decision
from domain.entities.transcript import Transcript, Segment
from interface.llm_services import ILLMService
from interface.transcriber import ITranscriber
from use_cases.transcribe_meeting import TranscribeMeetingUC, TranscribeMeetingInput
from use_cases.summarize_meeting import SummarizeMeetingUC, SummarizeMeetingInput  
from use_cases.chat_with_meeting import ChatWithMeetingUC, ChatWithMeetingInput  
from infrastructure.json_meeting_repository import JsonMeetingRepository  

"""
test_full_flow.py — Testa o fluxo completo usando mocks (sem gastar API).

Execute: pytest test_full.py -v

Útil para:
  - Validar que todas as camadas estão conectadas corretamente
  - Rodar em CI sem OPENAI_API_KEY
  - Desenvolver a UI sem depender de áudio real
"""

# Mocks — implementam as interfaces sem chamar API nenhuma, retornando dados fixos e realistas para testar o fluxo completo
# Mocks de classes de transcrição e LLM, que simulam o comportamento esperado sem realizar o processamento real, permitindo estabilizar o fluxo de dados e aintegração 
class MockTranscriber(ITranscriber):
    """Transcritor falso para testes."""

# Implementação de metodos de transcrição que retornam um Transcript fixo, 
# com texto formatado e segmentos de exemplo, que simula uma reunião de planejamentos 
    def transcribe(self, audio_path: str) -> Transcript:
        return Transcript(
            full_text=(
                "Bom dia a todos. Vamos começar com o ponto do onboarding. "
                "A Ana vai revisar o fluxo até sexta. "
                "O Carlos vai planejar o sprint de QA. "
                "Decidimos lançar a versão 2.0 em julho."
            ),
            language="pt",
            audio_path=audio_path,
        )
# Implementação de metodo de transcrição com diarização que retornam em Transcript com segmenntos preenchidos
    def transcribe_with_diarization(self, audio_path: str) -> Transcript:
        segments = [
            Segment(0.0, 4.0, "Speaker 0", "Bom dia a todos. Vamos começar com o ponto do onboarding."),
            Segment(5.5, 9.0, "Speaker 1", "A Ana vai revisar o fluxo até sexta."),
            Segment(10.0, 14.0, "Speaker 0", "O Carlos vai planejar o sprint de QA."),
            Segment(15.5, 19.0, "Speaker 1", "Decidimos lançar a versão 2.0 em julho."),
        ]
        full_text = " ".join(s.text for s in segments)
        return Transcript(
            full_text=full_text,
            segments=segments,
            language="pt",
            audio_path=audio_path,
        )

# Mock de classe de serviço de LLM, que simula a geração de resumo a resposta a perguntas, 
# retornando um Summary fixo e respostas pré-definidas para validar o fluxo de dados 
class MockLLMService(ILLMService):
    """LLM falso para testes."""

# Implementação de metodo de sumarização que retorna um Summary fixo, com visão geral, tópicos relevantes e tarefas 
    def summarize(self, transcript: str) -> Summary:
        return Summary(
            overview="Reunião de planejamento onde foram definidas tarefas de onboarding e QA, com lançamento da v2.0 marcado para julho.",
            topics=["Revisão do fluxo de onboarding", "Planejamento do sprint de QA", "Lançamento v2.0"],
            tasks=[
                Task("Revisar fluxo de onboarding", "Ana", "Sexta-feira"),
                Task("Planejar sprint de QA", "Carlos", "Não definido"),
            ],
            decisions=[
                Decision("Lançar versão 2.0 em julho", "Equipe alinhada com o roadmap do produto"),
            ],
        )

# Implementação de metodo de chat que retornam respostas pré-definidas para perguntas sobre a reunião, 
# simulando o comportamento de um assistente de reuniões 
    def chat(self, question: str, context: str, history: list[dict]) -> str:
        return (
            f"[Resposta mock para: '{question}']\n"
            "Ana ficou responsável por revisar o fluxo de onboarding até sexta-feira, "
            "conforme definido na reunião."
        )

# Fixtures
# Define um fixture que cria um Meeting completo a partir de transcrição

@pytest.fixture(scope="session")
def meeting():
    """Cria um Meeting completo para os testes"""
    uc = TranscribeMeetingUC(transcriber=MockTranscriber())
    result = uc.execute(TranscribeMeetingInput(
        audio_path="fake/audio.wav",
        with_diarization=True,
    ))
    
    t = result.transcript
    
    # Monta Meeting
    meeting = Meeting(
        id=str(uuid.uuid4()),
        title="Reunião de Teste — Sprint Planning",
        started_at=datetime.now(),
        audio_path="fake/audio.wav",
        transcript_text=t.full_text,
        transcript_formatted=t.formatted,
        participants=t.speakers,
        duration_minutes=t.duration_minutes,
    )
    
    # Adiciona summary ao meeting
    repo = JsonMeetingRepository(storage_path="data/test_meetings")
    summarize_uc = SummarizeMeetingUC(llm_service=MockLLMService(), repository=repo)
    summary_result = summarize_uc.execute(SummarizeMeetingInput(meeting=meeting))
    
    return summary_result.meeting if summary_result.success else meeting

# Testes
# Cada teste valida uma parte do fluxo completo: Transcrição - Reusmo - Chat _ Persistência,
#  utilizando os mocks para garantir que o fluxo de dados e a integração 

def test_transcricao():
    print("\n🧪 Teste 1 — Transcrição")
    print("-" * 40)

    uc = TranscribeMeetingUC(transcriber=MockTranscriber())
    result = uc.execute(TranscribeMeetingInput(
        audio_path="fake/audio.wav",
        with_diarization=True,
    ))

    assert result.success, f"Falhou: {result.error_message}"

    t = result.transcript
    print(f"✅ Idioma       : {t.language}")
    print(f"✅ Segmentos    : {len(t.segments)}")
    print(f"✅ Speakers     : {t.speakers}")
    print(f"✅ Formatado    :\n{t.formatted}")
    
    assert len(t.segments) > 0
    assert len(t.speakers) > 0

# Teste de resumo que valida a geração de reusmo a partir da transcrição, utilizando o MockLLMService para garantir 
def test_resumo(meeting: Meeting):
    print("\n🧪 Teste 2 — Resumo")
    print("-" * 40)

    assert meeting is not None
    assert meeting.is_summarized or meeting.summary is not None
    
    s = meeting.summary or Summary()
    print(f"✅ Visão geral  : {s.overview[:60] if s.overview else 'N/A'}...")
    print(f"✅ Tópicos      : {s.topics}")
    print(f"✅ Tarefas      : {[t.description for t in s.tasks]}")
    print(f"✅ Decisões     : {[d.description for d in s.decisions]}")

# Teste de chat que valida a resposta a perguntas sobre a reunião, utilizando o MockLLMService para simualar o comportamento
def test_chat(meeting: Meeting):
    print("\n🧪 Teste 3 — Chat")
    print("-" * 40)

    uc = ChatWithMeetingUC(llm_service=MockLLMService())

    perguntas = [
        "Quem ficou responsável pelo onboarding?",
        "Quando vai ser lançada a versão 2.0?",
    ]

    history = []
    for pergunta in perguntas:
        result = uc.execute(ChatWithMeetingInput(
            meeting=meeting,
            question=pergunta,
            history=history,
        ))
        assert result.success, f"Falhou: {result.error_message}"
        print(f"\n  Pergunta : {pergunta}")
        print(f"  Resposta : {result.answer[:100] if result.answer else 'N/A'}...")
        history.append({"role": "user", "content": pergunta})
        history.append({"role": "assistant", "content": result.answer})

# Teste de persistência que valida a capacidade de salvar e carregar a reuniao usando o JsonMeetingRepository,
#  garantindo que a serialização e deserialização estão funcionando corretamente
def test_persistencia(meeting: Meeting):
    print("\n🧪 Teste 4 — Persistência (JSON)")
    print("-" * 40)

    repo = JsonMeetingRepository(storage_path="data/test_meetings")
    repo.save(meeting)
    print(f"✅ Salvo: data/test_meetings/{meeting.id}.json")

    loaded = repo.find_by_id(meeting.id)
    assert loaded is not None
    assert loaded.title == meeting.title
    print(f"✅ Carregado    : {loaded.title}")
    if loaded.summary:
        print(f"✅ Resumo OK    : {loaded.summary.overview[:60]}...")

    all_meetings = repo.list_all()
    print(f"✅ Total salvo  : {len(all_meetings)} reunião(ões)")