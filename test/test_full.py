# Testa o fluxo completo do Meet Agent usando mocks para transcrição e LLM, sem gastar API calls
import sys
import os
import uuid
from datetime import datetime

# Adiciona o diretório raiz ao path para permitir imports relativos
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# CORRIGIDO: Imports ajustados para a estrutura real do projeto
from entities.metting import Meeting, Summary, Task, Decision
from entities.transcript import Transcript, Segment
from interface.llm_services import ILLMService
from interface.transcriber import ITranscriber
from user_cases.transcribe_meeting import TranscribeMeetingUC, TranscribeMeetingInput
from user_cases.summarize_metting import SummarizeMeetingUC, SummarizeMeetingInput  # CORRIGIDO: summarize_meeting → summarize_metting
from user_cases.chat_with_meeting import ChatWithMeetingUC, ChatWithMeetingInput  # CORRIGIDO: faltava este import
from infraestrutura.json_meeting_repor import JsonMeetingRepository  # CORRIGIDO: repositores → infraestrutura

"""
test_full_flow.py — Testa o fluxo completo usando mocks (sem gastar API).

Execute: python test_full_flow.py

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

# Testes
# Cada teste valida uma parte do fluxo completo: Transcrição - Reusumo - Chat _ Persistência,
#  utilizando os mocks para garantir que o fluxo de dados e a integração 
def test_transcricao() -> Meeting:
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

    # Monta Meeting para próximos testes
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
    return meeting

# Teste de resumo que valida a geração de reusmo a partir da transcrição, utilizando o MockLLMService para garantir 
def test_resumo(meeting: Meeting) -> Meeting:
    print("\n🧪 Teste 2 — Resumo")
    print("-" * 40)

    repo = JsonMeetingRepository(storage_path="data/test_meetings")
    uc = SummarizeMeetingUC(llm_service=MockLLMService(), repository=repo)
    result = uc.execute(SummarizeMeetingInput(meeting=meeting))

    assert result.success, f"Falhou: {result.error_message}"

    s = result.summary  # CORRIGIDO: result.meeting.summary → result.summary
    print(f"✅ Visão geral  : {s.overview[:60]}...")
    print(f"✅ Tópicos      : {s.topics}")
    print(f"✅ Tarefas      : {[t.description for t in s.tasks]}")
    print(f"✅ Decisões     : {[d.description for d in s.decisions]}")

    return meeting  # CORRIGIDO: result.meeting → meeting (que foi atualizado com o summary)

# Teste de chat que valida a resposta a perguntas sobre a reunião, utilizando o MockLLMService para simualar o comportamento
def test_chat(meeting: Meeting) -> None:
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
        print(f"  Resposta : {result.answer[:100]}...")
        history.append({"role": "user", "content": pergunta})
        history.append({"role": "assistant", "content": result.answer})

# Teste de persistência que valida a capacidade de salvar e carregar a reuniao usando o JsonMeetingRepository,
#  garantindo que a serialização e deserialização estão funcionando corretamente
def test_persistencia(meeting: Meeting) -> None:
    print("\n🧪 Teste 4 — Persistência (JSON)")
    print("-" * 40)

    repo = JsonMeetingRepository(storage_path="data/test_meetings")
    repo.save(meeting)
    print(f"✅ Salvo: data/test_meetings/{meeting.id}.json")

    loaded = repo.find_by_id(meeting.id)
    assert loaded is not None
    assert loaded.title == meeting.title
    assert loaded.is_summarized
    print(f"✅ Carregado    : {loaded.title}")
    print(f"✅ Resumo OK    : {loaded.summary.overview[:60]}...")

    all_meetings = repo.list_all()
    print(f"✅ Total salvo  : {len(all_meetings)} reunião(ões)")
# Runner
# Executa os testes em sequencia para evitar dependencias entre elas, validando o fluxo completo do Meet Agente com os mocks 
if __name__ == "__main__":
    print("=" * 50)
    print("🚀 Meet Agent — Teste do Fluxo Completo (mock)")
    print("=" * 50)

    try:
        meeting = test_transcricao()
        meeting = test_resumo(meeting)
        test_chat(meeting)
        test_persistencia(meeting)

        print("\n" + "=" * 50)
        print("✅ Todos os testes passaram!")
        print("\nPróximo passo:")
        print("  1. Configure sua .env com OPENAI_API_KEY")
        print("  2. python main.py --test <seu_audio.wav>")
        print("  3. python main.py  →  abre o Streamlit")
        print("=" * 50)

    except AssertionError as e:
        print(f"\n❌ Teste falhou: {e}")
        sys.exit(1)