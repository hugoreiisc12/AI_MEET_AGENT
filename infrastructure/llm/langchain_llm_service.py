import json
import re
from datetime import datetime
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, BaseMessage
from pydantic import SecretStr

from domain.entities.meeting import Summary, Task, Decision, Meeting
from domain.entities.meeting_type import MeetingType
from interface.llm_services import ILLMService, LLMServiceError
from config.settings import get_settings
from infrastructure.llm.prompt_builder import PromptBuilder

CHAT_SYSTEM_PROMPT = """Você é o Meet Agent, um assistente de reuniões especializado, educado e receptivo.

Você participou da reunião abaixo e pode responder perguntas sobre ela.

TRANSCRIÇÃO DA REUNIÃO:
{transcript}

SUMÁRIO DA REUNIÃO:
{summary}

=== REGRAS DE CONDUTA ===

1. IDIOMA:
   - Responda SEMPRE em português do Brasil.
   - Mesmo que a transcrição tenha trechos em outros idiomas, sua resposta deve ser em português.

2. TOM E POSTURA:
   - Seja educado, receptivo e profissional. Use um tom cordial e acolhedor.
   - Inicie a conversa com "Como posso te ajudar?" ou uma saudação amigável.
   - Antes de confirmar uma tarefa, pergunte "Posso confirmar o envio dessa tarefa?".
   - Após concluir uma tarefa ou responder, pergunte "Atendi suas expectativas?" ou "Como podemos prosseguir?".
   - Ao encerrar, diga "Muito obrigado pela conversa e tenha um ótimo dia!".
   - Responda com clareza e objetividade, mas de forma agradável e elegante.
   - Agradeça pela pergunta ou interação quando apropriado.
   - NÃO seja seco ou robótico — pareça uma pessoa educada ajudando.
   - Seja completo e contextual: não responda com frases curtas e vagas. Forneça
     informações detalhadas e úteis sempre que possível.

3. ACURÁCIA, FIDELIDADE E HONESTIDADE:
   - ANTES DE RESPONDER, analise profundamente a pergunta. Reflita sobre o que foi perguntado.
   - Seja absolutamente FIEL ao que foi dito na reunião. Sua resposta deve refletir
     APENAS o que consta na transcrição, sem acréscimos ou invenções.
   - NÃO invente fatos, números, prazos, nomes ou decisões que não estejam explícitos
     ou implicitamente evidentes na transcrição.
   - Se não souber a resposta ou se o assunto não foi mencionado na reunião, diga
     educadamente: "Essa informação não foi mencionada durante a reunião." ou
     "Não encontrei esse ponto na transcrição." — NUNCA invente uma resposta.
   - NÃO confunda participantes mencionados na conversa com participantes reais da reunião.
   - Participantes da reunião são APENAS as pessoas que efetivamente falaram ou estavam presentes na reunião.
   - Se alguém foi citado durante a conversa, isso não significa que essa pessoa era um participante.
   - Ao perguntarem quantos participantes tinha, retorne APENAS os participantes reais que falaram na reunião.
   - Se você estiver interpretando algo (e não citando diretamente), deixe isso
     EXPLICITAMENTE claro na sua resposta.

4. ESCOPO DAS RESPOSTAS:
   - Você pode responder perguntas sobre QUALQUER aspecto relacionado à reunião: participantes, decisões, tarefas, agenda, tópicos, sentimentos, duração, etc.
   - Se a resposta não estiver explícita na transcrição, use o contexto disponível para oferecer uma resposta útil, mas SEMPRE deixe claro quando está interpretando vs. quando está citando a transcrição.
   - Para perguntas fora do escopo da reunião, oriente educadamente o usuário a perguntar sobre a reunião.

5. FORMATAÇÃO:
   - Responda sempre em português do Brasil.
   - Use os identificadores reais dos participantes (e-mails ou nomes) ao se referir a quem disse algo.
   - Seja direto e objetivo, mas com elegância.
   - Suas respostas devem ser completas, informativas e contextualizadas — nunca
     monossilábicas ou vagas demais.

6. IDENTIFICAÇÃO DO USUÁRIO:
   {user_context}

=== CRIAÇÃO DE TAREFAS ===

Você pode criar tarefas para a reunião de duas formas:

FORMA 1 — DETECÇÃO AUTOMÁTICA:
Quando o usuário mencionar frases como "vamos estar criando", "vamos pegar esse ponto", "fazendo essa melhoria", "precisamos fazer", "vamos criar", "criar uma tarefa" ou similares, você DEVE iniciar o fluxo de criação.

FORMA 2 — SOLICITAÇÃO DIRETA:
Se o usuário pedir "crie uma tarefa", "quero criar uma tarefa", "adicionar tarefa", etc., inicie o mesmo fluxo.

FLUXO DE CRIAÇÃO:
1. Converse com o usuário para coletar UMA POR UMA as seguintes informações:
   a) Nome da tarefa (obrigatório)
   b) Responsável pela tarefa (quem vai executar)
   c) Para quem é a tarefa (destinatário/atribuído)
   d) Prazo de entrega (pergunte se tem prazo; se não, marcar como "Indefinido")
   e) E-mail do destinatário (para envio da tarefa) — se o usuário não informar, use o e-mail padrão do sistema
2. Seja natural e conversacional — colete um campo por vez, como uma conversa normal.
3. Após coletar TUDO, apresente um resumo claro com todos os dados e pergunte "Posso confirmar o envio dessa tarefa?".
4. Se o usuário confirmar ("sim", "pode confirmar", "confirmo", etc.), inclua no FINAL da sua resposta o marcador abaixo com os dados em JSON.

---TAREFA---
{{"nome": "nome completo da tarefa", "responsavel": "nome do responsável", "destinatario": "para quem é", "prazo": "prazo ou Indefinido", "email": "email do destinatário", "criada_em": "data e hora atual", "descricao": "descrição detalhada do que precisa ser feito"}}
[/TAREFA]

5. Se o usuário quiser alterar algo, ajuste conforme solicitado e repita a confirmação.
6. NÃO invente tarefas. Só crie quando o usuário pedir ou quando houver uma solicitação clara na conversa."""


class LangChainLLMService(ILLMService):
    """Serviço de LLM local via Ollama (LangChain + OpenAI-compatible API)."""

    def __init__(self, llm: ChatOpenAI | None = None) -> None:
        settings = get_settings()
        self._prompt_builder = PromptBuilder()
        self._current_transcript: str = ""

        if llm:
            self._llm = llm
        else:
            self._llm = ChatOpenAI(
                model=getattr(settings, "ollama_model", "nemotron-mini"),
                api_key=SecretStr("ollama"),
                base_url=getattr(settings, "ollama_base_url", "http://localhost:11434/v1"),
                temperature=settings.llm_temperature,
                top_p=settings.llm_top_p,
            )

    def summarize(self, transcript: str, meeting_type: MeetingType = MeetingType.GENERAL) -> Summary:
        try:
            system_prompt = self._prompt_builder.build_summarize_system(meeting_type)
            user_message  = self._prompt_builder.build_summarize_user(transcript)
            messages: list[BaseMessage] = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_message),
            ]
            response = self._llm.invoke(messages)
            content  = response.content if isinstance(response.content, str) else str(response.content)
            return self._parse_summary(content)
        except LLMServiceError:
            raise
        except Exception as e:
            raise LLMServiceError(f"Falha na sumarização: {str(e)}") from e

    def chat(self, question: str, context: str, history: list[dict], summary_context: str = "", user_id: str | None = None) -> str:
        try:
            user_context = ""
            if user_id:
                user_context = f"O usuário que está perguntando é {user_id}."
            messages: list[BaseMessage] = [
                SystemMessage(content=CHAT_SYSTEM_PROMPT.format(
                    transcript=context,
                    summary=summary_context or "Nenhum sumário disponível.",
                    user_context=user_context,
                ))
            ]
            for turn in history:
                if turn["role"] == "user":
                    messages.append(HumanMessage(content=turn["content"]))
                else:
                    messages.append(AIMessage(content=turn["content"]))
            messages.append(HumanMessage(content=question))
            response = self._llm.invoke(messages)
            content  = response.content if isinstance(response.content, str) else str(response.content)
            return content
        except LLMServiceError:
            raise
        except Exception as e:
            raise LLMServiceError(f"Falha no chat: {str(e)}") from e

    @staticmethod
    def parse_task_from_response(response: str) -> dict | None:
        match = re.search(
            r"---TAREFA---\s*\n?(\{.*?\})\n?\[/TAREFA\]",
            response,
            re.DOTALL,
        )
        if not match:
            return None
        raw_json = match.group(1).strip()
        try:
            return json.loads(raw_json)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def generate_task_email_content(task_data: dict, meeting: Meeting) -> str:
        from infrastructure.email.email_sender import TASK_TEMPLATE
        meeting_title = meeting.title or "Reunião"
        meeting_date = meeting.started_at.strftime("%d/%m/%Y às %H:%M") if meeting.started_at else datetime.now().strftime("%d/%m/%Y às %H:%M")
        meeting_link = meeting.id or "Não informado"
        return TASK_TEMPLATE.format(
            meeting_title=meeting_title,
            meeting_date=meeting_date,
            task_name=task_data.get("nome", "Sem nome"),
            created_at=task_data.get("criada_em", datetime.now().strftime("%d/%m/%Y %H:%M")),
            deadline=task_data.get("prazo", "Indefinido"),
            description=task_data.get("descricao", "Sem descrição"),
            meeting_link=meeting_link,
        )

    @staticmethod
    def strip_task_marker(response: str) -> str:
        return re.sub(
            r"\n?---TAREFA---\s*\n?\{.*?\}\n?\[/TAREFA\]",
            "",
            response,
            flags=re.DOTALL,
        ).strip()

    def _parse_summary(self, raw: str) -> Summary:
        cleaned = self._extract_json(raw)
        try:
            data: dict = json.loads(cleaned)
        except (json.JSONDecodeError, KeyError) as e:
            recovered = self._recover_invalid_json(cleaned)
            try:
                data = json.loads(recovered)
            except Exception:
                raise LLMServiceError(
                    f"JSON inválido da LLM: {str(e)}\nResposta: {raw[:300]}"
                ) from e

        tasks = [
            Task(
                description=t.get("description", ""),
                responsible=t.get("responsible", "Não definido"),
                deadline=t.get("deadline", "Não definido"),
            )
            for t in data.get("tasks", [])
        ]
        decisions = [
            Decision(
                description=d.get("description", ""),
                context=d.get("context", ""),
            )
            for d in data.get("decisions", [])
        ]
        return Summary(
            overview=data.get("overview", ""),
            topics=data.get("topics", []),
            tasks=tasks,
            decisions=decisions,
        )

    def _extract_json(self, raw: str) -> str:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            parts = cleaned.split("```")
            if len(parts) >= 3:
                if parts[1].strip().lower().startswith("json"):
                    cleaned = parts[2]
                else:
                    cleaned = parts[1]
            else:
                cleaned = cleaned.replace("```", "")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned.split("\n", 1)[-1]
        cleaned = cleaned.strip()
        first_brace = cleaned.find("{")
        if first_brace != -1:
            cleaned = cleaned[first_brace:]
        return cleaned.strip()

    def _recover_invalid_json(self, raw: str) -> str:
        candidate = raw.strip()
        candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
        brace_balance = 0
        bracket_balance = 0
        for ch in candidate:
            if ch == "{":
                brace_balance += 1
            elif ch == "}":
                brace_balance -= 1
            elif ch == "[":
                bracket_balance += 1
            elif ch == "]":
                bracket_balance -= 1
        if brace_balance > 0:
            candidate += "}" * brace_balance
        if bracket_balance > 0:
            candidate += "]" * bracket_balance
        return candidate
