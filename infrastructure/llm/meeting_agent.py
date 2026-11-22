"""Agente de reuniões em LangGraph, regido pelo contrato SPEC_CONTRACT.md (ADR-014).

Dois grafos atrás da porta ILLMService (casos de uso, API e interface não mudam):

  chat:   responder (pode pedir uma ferramenta) → verificar ─ ok ──► fim
                         └─ violou → responder de novo (com as violações) → verificar
                         └─ violou de novo → resposta padrão de "elementos insuficientes"
          Ferramentas: send_email e create_document. O texto do e-mail ou do documento passa
          pela mesma verificação de contrato que uma resposta. Quem executa é o caso de uso.

  resumo: gerar → validar JSON ─ ok ─► normalizar (status da decisão, responsáveis) → fim
                     └─ inválido → gerar de novo (com o erro) ─ inválido de novo → erro

O contrato vai inteiro no prompt de sistema. As regras que dão para conferir sem
outro modelo ficam em use_cases/contract_checks.py.
"""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from config.settings import get_settings
from domain.entities.meeting import Decision, Summary, Task
from domain.entities.meeting_type import MeetingType
from domain.interfaces.llm_service import ChatReply, ILLMService, LLMServiceError
from infrastructure.llm.model_client import ContextBudget, ModelClient
from infrastructure.llm.prompt_builder import PromptBuilder
from use_cases.contract_checks import FALLBACK, check_answer, decision_status, responsible_or_undefined

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2  # primeira resposta + uma correção
SMALL_WINDOW = 16000  # tokens; abaixo disso o resumo usa o contrato compacto


@lru_cache(maxsize=1)
def load_contract(path: str) -> str:
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parents[2] / p
    if not p.exists():
        raise LLMServiceError(f"Contrato do agente não encontrado: {p} (AGENT_CONTRACT_PATH)")
    return p.read_text(encoding="utf-8").strip()


CHAT_RULES = """REGRAS DE OPERAÇÃO NESTE SISTEMA (complementam o contrato acima):
1. Você responde sobre UMA reunião, usando apenas o CONTEXTO DA REUNIÃO abaixo. Em reuniões longas o
   contexto traz o resumo e só os trechos da transcrição ligados à pergunta.
   O que foi buscado para cada pergunta (trechos da transcrição, registros de outras reuniões, notas do
   usuário) vem junto com a pergunta, na mensagem do usuário, e também é contexto.
2. Outras reuniões do mesmo usuário só chegam a você pelo bloco "REGISTROS DE OUTRAS REUNIÕES" (§14),
   e pelas FALAS DE OUTRAS REUNIÕES, quando existirem no contexto: cite de qual reunião e data veio cada
   item e não trate decisão antiga como vigente sem checar se foi revista. Ao responder sobre uma
   decisão, tarefa ou responsável da reunião aberta, diga também se uma REUNIÃO POSTERIOR do bloco a
   revisou ou definiu (ex.: tarefa sem dono na reunião aberta que ganhou responsável depois). O que não estiver nesse bloco, você não
   acessa: diga isso.
3. Antes de concluir que um assunto não aparece, procure-o com outras palavras: a pergunta pode usar
   sinônimo ou paráfrase do que foi dito (ex.: "serviço de mensageria" = "fila de mensagens"; "quanto
   custa" = "cobra", "valor", "preço"). Se mesmo assim o assunto não aparece no contexto, responda só:
   "Isso não foi mencionado durante a reunião." Nunca diga isso e depois responda sobre o assunto.
4. Ao citar uma fala entre aspas, copie exatamente o texto da transcrição. Só atribua falas a quem as fez.
5. Separe o que foi dito do que é interpretação sua (§4). Proposta não é decisão; silêncio não é concordância.
6. Pergunta direta pede resposta direta. Pedido de "análise completa" ou "ata" segue o formato do §13.
   Pergunta sobre o que você achou da reunião segue o §11.
7. Responda em português do Brasil, salvo se a pergunta for feita em outro idioma.
   Escreva em português do Brasil correto: concordância, acentos e pontuação, frases curtas e diretas, sem repetir a mesma ideia.
   A transcrição automática erra palavras: em texto seu (fora de aspas), se um termo não existe em português ou destoa do
   assunto e a palavra certa é óbvia pelo contexto (ex.: "matriologia" no lugar de "metodologia"), use a forma certa; se
   houver dúvida, mantenha o termo como está. Dentro de aspas, copie exatamente. Não afirme duração, nomes, números ou
   quem informou algo se isso não está no contexto, e não se contradiga (se um assunto foi mencionado, não diga que
   não foi discutido: diga que foi só citado).
8. Ferramentas: use `send_email` só quando o usuário pedir para enviar um e-mail e informar o
   endereço; nunca invente endereço. Se pedirem um e-mail sem dizer o endereço, não use a
   ferramenta: peça o endereço de cada destinatário. Para e-mail COM arquivo anexo, use
   `send_email` com `attach_documents` (documento já gerado na conversa) ou `attachment` (arquivo
   novo); nunca diga que anexou algo sem preencher um dos dois. Use `create_document` só quando ele pedir um arquivo (PDF,
   Word, Excel, CSV, planilha, HTML, dashboard, gráfico, documento, ata em arquivo); se ele pedir
   "aqui", "no chat" ou "escreva", responda em texto. Use `remember` só
   quando o usuário pedir para você lembrar de algo ou declarar uma preferência para as próximas vezes.
   Use `search_meetings` (quando existir) se a resposta depender de outra reunião do usuário e o
   contexto não trouxer o necessário; depois responda com o que voltar, citando [Título · data · horário]. O texto do e-mail ou do documento segue as mesmas regras de
   fidelidade acima. Para qualquer outra pergunta, responda em texto, sem ferramenta.

CONTEXTO DA REUNIÃO:
{context}"""

SUMMARY_RULES = """Você vai produzir o registro estruturado da reunião em JSON, seguindo o contrato acima,
em especial os §4 (fidelidade), §6 (requisitos) e §7 (decisões). Responda APENAS com o JSON.
Escreva em português do Brasil correto: concordância, acentos e pontuação, frases curtas e diretas, sem repetir a mesma ideia.
A transcrição automática erra palavras: em texto seu (fora de aspas), se um termo não existe em português ou destoa do
assunto e a palavra certa é óbvia pelo contexto (ex.: "matriologia" no lugar de "metodologia"), use a forma certa; se
houver dúvida, mantenha o termo como está. Dentro de aspas, copie exatamente. Não afirme duração, nomes, números ou
quem informou algo se isso não está no contexto, e não se contradiga (se um assunto foi mencionado, não diga que
não foi discutido: diga que foi só citado)."""


TOOLS = [
    {"type": "function", "function": {
        "name": "send_email",
        "description": "Prepara um e-mail sobre a reunião para os destinatários que o usuário informou. "
                       "O usuário confirma antes do envio.",
        "parameters": {"type": "object", "required": ["to", "subject", "body"], "properties": {
            "to": {"type": "array", "items": {"type": "string"},
                   "description": "Endereços exatamente como o usuário escreveu"},
            "subject": {"type": "string"},
            "body": {"type": "string", "description": "Texto do e-mail, fiel à reunião"},
            "attach_documents": {"type": "boolean", "description": (
                "true para anexar ao e-mail os documentos que já foram gerados nesta conversa")},
            "attachment": {"type": "object", "description": (
                "Arquivo a gerar agora e anexar (quando o usuário pede o e-mail com um arquivo novo)"),
                "required": ["format", "title", "content"], "properties": {
                    "format": {"type": "string", "enum": ["pdf", "docx", "xlsx", "csv", "html", "md"]},
                    "title": {"type": "string"},
                    "content": {"type": "string", "description": "Conteúdo em Markdown, fiel à reunião"},
                }},
        }}}},
    {"type": "function", "function": {
        "name": "create_document",
        "description": "Gera um arquivo para download com conteúdo da reunião (ata, decisões, tarefas, resumo, "
                       "planilha, dashboard com gráficos).",
        "parameters": {"type": "object", "required": ["format", "title", "content"], "properties": {
            "format": {"type": "string", "enum": ["pdf", "docx", "xlsx", "csv", "html", "md"],
                       "description": "pdf; docx (Word); xlsx (Excel) ou csv (planilha); html (página com "
                                      "tabelas e gráficos, para dashboard); md (Markdown)"},
            "title": {"type": "string"},
            "content": {"type": "string", "description": (
                "Conteúdo em Markdown, fiel à reunião: títulos ##, listas -, tabelas | col | col |. "
                "Para xlsx, csv e html, ponha os dados em tabelas Markdown; no html, cada tabela com "
                "uma coluna numérica (ex.: tarefas por responsável) vira um gráfico de barras.")},
        }}}},
    {"type": "function", "function": {
        "name": "remember",
        "description": "Guarda uma nota que o usuário pediu para lembrar nas próximas conversas, de qualquer "
                       "reunião (preferência de formato, quem é quem, contexto do projeto).",
        "parameters": {"type": "object", "required": ["note"], "properties": {
            "note": {"type": "string", "description": "A nota, curta, nas palavras do usuário"},
        }}}},
]


DIGEST_CHARS = 3000
_FIRST_SENTENCE = re.compile(r"^(.{1,200}?[.!?])(\s|$)", re.DOTALL)


def conversation_digest(old: list[dict]) -> str:
    """Resumo corrido das mensagens que saíram da janela, sem chamar o modelo. As do usuário vêm
    inteiras (até 300 caracteres): é nelas que fica o que foi combinado. Das respostas, só a
    primeira frase, e só se couber. Passando do teto, ficam as mais antigas (o início da conversa)."""
    user = [(i, "Usuário: " + m["content"].strip()[:300]) for i, m in enumerate(old) if m["role"] == "user"]
    agent = [(i, "Agente: " + ((_FIRST_SENTENCE.match(m["content"].strip()) or [None, m["content"].strip()[:200]])[1]))
             for i, m in enumerate(old) if m["role"] == "assistant"]
    lines, size = [], 0
    for i, line in user + agent:  # usuário primeiro: é o que não pode se perder
        if size + len(line) + 1 > DIGEST_CHARS:
            continue
        lines.append((i, line))
        size += len(line) + 1
    body = "\n".join(line for _, line in sorted(lines))
    return ("RESUMO DO INÍCIO DESTA CONVERSA (mensagens antigas que não cabem mais na íntegra; o que o usuário "
            f"pediu ou combinou nelas continua valendo):\n{body}")


SEARCH_TOOL = {"type": "function", "function": {
    "name": "search_meetings",
    "description": "Busca falas nas OUTRAS reuniões do usuário quando o contexto não basta para responder "
                   "(ex.: o que foi dito antes sobre um assunto, quem assumiu uma tarefa em outra reunião).",
    "parameters": {"type": "object", "required": ["query"], "properties": {
        "query": {"type": "string", "description": "O que procurar, em poucas palavras"},
    }}}}


def _tool_text(tool: Optional[dict]) -> str:
    """O texto que a ferramenta vai entregar a alguém: é ele que passa pela verificação.
    Títulos (linhas com #) e linhas que são só um texto entre aspas ficam de fora: são
    cabeçalho do documento, não fala de alguém da reunião. Citações no meio do texto continuam."""
    if not tool:
        return ""
    args = tool.get("arguments") or {}
    text = str(args.get("body") or args.get("content") or "")
    attachment = args.get("attachment")
    if isinstance(attachment, dict):
        text += "\n" + str(attachment.get("content") or "")
    keep = [line for line in text.splitlines()
            if not line.lstrip().startswith("#") and not _QUOTED_LINE.fullmatch(line.strip())]
    # Aspas sem ninguém falando antes (título, nome de documento) perdem as aspas; as que vêm
    # depois de "disse", "afirmou", "Nome:" etc. continuam sendo conferidas com a transcrição.
    return _QUOTE_ANY.sub(lambda m: m.group(0) if _SPEECH.search(m.string[max(0, m.start() - 40):m.start()])
                          else m.group(1), "\n".join(keep))


_CLAIMS_ACTION = re.compile(r"\b(gerei|criei|preparei|enviei|anexei)\b[^.\n]{0,40}\b(documento|arquivo|pdf|"
                            r"word|docx|markdown|e-?mail)", re.IGNORECASE)
# O modelo copiou a nota interna do histórico ("[O sistema executou a ferramenta…]") em vez de chamar a ferramenta.
_COPIED_NOTE = re.compile(r"o sistema executou a ferramenta|\bsend_email\b|\bcreate_document\b", re.IGNORECASE)
# Pedido de memória ("lembre", "anote", "prefiro", "de agora em diante"); sem ele, remember é engano do modelo
# (eval de 2026-11-21: "O que ficou em aberto?" virou nota gravada).
_WANTS_MEMORY = re.compile(r"lembr|anot|guard|memoriz|grav[ae]|salv[ae]|prefir|prefer|daqui (pra|para) frente|"
                           r"de agora em diante|sempre que|nas próximas", re.IGNORECASE)
_QUOTED_LINE = re.compile(r"[*_]*[\"“][^\"“”]+[\"”][*_]*")
_QUOTE_ANY = re.compile(r"[\"“]([^\"“”\n]+)[\"”]")
_SPEECH = re.compile(r"(disse|diz|afirmou|falou|comentou|declarou|perguntou|respondeu|explicou|"
                     r"segundo \w+|nas palavras d\w+|:)\s*$", re.IGNORECASE)


class ChatState(TypedDict, total=False):
    question: str
    context: str
    question_context: str
    can_search: bool
    on_delta: object  # Callable[[str], None] | None: texto aos pedaços (S16-2)
    history: list[dict]
    answer: str
    tool: Optional[dict]
    violations: list[str]
    attempts: int


class SummaryState(TypedDict, total=False):
    transcript: str
    meeting_type: MeetingType
    raw: str
    error: str
    attempts: int
    summary: Optional[Summary]


class MeetingAgent(ILLMService):
    def __init__(self, model: Optional[ModelClient] = None, contract: Optional[str] = None) -> None:
        settings = get_settings()
        self._model = model or ModelClient()
        profile = getattr(self._model, "profile", None)
        self._budget = ContextBudget(profile.context_tokens if profile else ModelClient(settings).profile.context_tokens)
        if contract is not None:
            self._contract = self._chat_contract = contract
        elif settings.memory_v2:
            self._chat_contract = load_contract(settings.agent_chat_contract_path)
            # O completo tem ~12 mil tokens: em janela abaixo de 16k não sobra lugar para a transcrição.
            small = self._budget.window_tokens < SMALL_WINDOW
            self._contract = self._chat_contract if small else load_contract(settings.agent_contract_v2_path)
        else:
            self._contract = self._chat_contract = load_contract(settings.agent_contract_path)
        self._prompts = PromptBuilder()
        self._chat_graph = self._build_chat_graph()
        self._summary_graph = self._build_summary_graph()

    # ── Porta ILLMService ─────────────────────────────────────────────

    def chat(self, question: str, context: str, history: list[dict], summary_context: str = "",
             user_id: str | None = None, question_context: str = "", can_search: bool = False,
             on_delta=None) -> ChatReply:
        state = self._chat_graph.invoke({"question": question, "context": context, "history": history,
                                         "question_context": question_context, "can_search": can_search,
                                         "on_delta": on_delta,
                                         "attempts": 0, "violations": [], "tool": None})
        return ChatReply(state["answer"], state.get("tool"))

    def summarize(self, transcript: str, meeting_type: MeetingType = MeetingType.GENERAL) -> Summary:
        state = self._summary_graph.invoke({"transcript": transcript, "meeting_type": meeting_type, "attempts": 0})
        if state.get("summary") is None:
            raise LLMServiceError(f"JSON inválido do modelo após {MAX_ATTEMPTS} tentativas: {state.get('error')}")
        return state["summary"]

    # ── Chat ──────────────────────────────────────────────────────────

    def _build_chat_graph(self):
        g = StateGraph(ChatState)
        g.add_node("answer", self._answer)
        g.add_node("verify", self._verify)
        g.add_node("fallback", lambda s: {"answer": FALLBACK, "tool": None})
        g.add_edge(START, "answer")
        g.add_edge("answer", "verify")
        g.add_conditional_edges("verify", self._after_verify, ["answer", "fallback", END])
        g.add_edge("fallback", END)
        return g.compile()

    def _answer(self, s: ChatState) -> ChatState:
        system = f"{self._chat_contract}\n\n{CHAT_RULES.format(context=s['context'])}"
        extra = s.get("question_context") or ""
        question = f"{extra}\nPERGUNTA: {s['question']}" if extra else s["question"]
        history = [{"role": t["role"], "content": t["content"]} for t in s.get("history", [])]
        tools = TOOLS + [SEARCH_TOOL] if s.get("can_search") else TOOLS
        kept = self._budget.fit_history(history, system, question, json.dumps(tools), " " * DIGEST_CHARS)
        if len(kept) < len(history):  # memória curta (S13-4): o que não coube vira resumo corrido
            kept = [{"role": "user", "content": conversation_digest(history[:len(history) - len(kept)])}, *kept]
        messages = [{"role": "system", "content": system}, *kept, {"role": "user", "content": question}]
        if s.get("violations"):
            messages += [
                {"role": "assistant", "content": s["answer"] or _tool_text(s.get("tool"))},
                {"role": "user", "content": "Sua resposta anterior violou o contrato: " + "; ".join(s["violations"])
                 + ". Responda de novo ao mesmo pedido, corrigindo isso e sem mencionar esta correção."
                 + (" Ao citar uma fala, copie a linha do contexto exatamente como está (horário, nome e texto); "
                    "se não for copiar literalmente, conte com suas palavras, sem colchetes nem aspas."
                    if any("confere" in v or "citação" in v for v in s["violations"]) else "")},
            ]
        # Só a primeira tentativa sai aos pedaços; a correção (se houver) chega inteira e substitui o texto.
        on_delta = s.get("on_delta") if not s.get("violations") else None
        if on_delta and hasattr(self._model, "complete_tools_stream"):
            answer, tool = self._model.complete_tools_stream(messages, tools, on_delta)
        else:
            answer, tool = self._model.complete_tools(messages, tools)
        return {"answer": answer.strip(), "tool": tool, "attempts": s.get("attempts", 0) + 1}

    def _verify(self, s: ChatState) -> ChatState:
        if (s.get("tool") or {}).get("name") == "search_meetings":
            return {"violations": []}  # pedido de busca: a resposta de verdade vem depois e é conferida
        if (s.get("tool") or {}).get("name") == "remember":
            if _WANTS_MEMORY.search(s["question"]):
                return {"violations": []}  # nota do próprio usuário: não é conteúdo da reunião a conferir
            return {"violations": ["usou remember sem o usuário pedir para lembrar algo; responda à pergunta em texto"]}
        text = _tool_text(s.get("tool")) or s["answer"]
        violations = check_answer(text, f"{s['context']}\n{s.get('question_context') or ''}", s["question"])
        if not s.get("tool") and (_CLAIMS_ACTION.search(s["answer"]) or _COPIED_NOTE.search(s["answer"])):
            violations.append("diz que gerou o arquivo ou preparou o e-mail sem usar a ferramenta; "
                              "use create_document ou send_email")
        if violations:
            logger.warning("Resposta violou o contrato (tentativa %d): %s", s["attempts"], "; ".join(violations))
        return {"violations": violations}

    @staticmethod
    def _after_verify(s: ChatState) -> str:
        if not s["violations"]:
            return END
        return "answer" if s["attempts"] < MAX_ATTEMPTS else "fallback"

    # ── Resumo ────────────────────────────────────────────────────────

    def _build_summary_graph(self):
        g = StateGraph(SummaryState)
        g.add_node("generate", self._generate)
        g.add_node("parse", self._parse)
        g.add_edge(START, "generate")
        g.add_edge("generate", "parse")
        g.add_conditional_edges(
            "parse",
            lambda s: END if s.get("summary") is not None or s["attempts"] >= MAX_ATTEMPTS else "generate",
            ["generate", END],
        )
        return g.compile()

    def _generate(self, s: SummaryState) -> SummaryState:
        system = f"{self._contract}\n\n{SUMMARY_RULES}\n\n{self._prompts.build_summarize_system(s['meeting_type'])}"
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": self._prompts.build_summarize_user(s["transcript"])}]
        if s.get("error"):
            messages += [{"role": "assistant", "content": s["raw"]},
                         {"role": "user", "content": f"O JSON acima é inválido ({s['error']}). "
                                                     "Devolva apenas o JSON completo e válido."}]
        return {"raw": self._model.complete(messages, as_json=True), "attempts": s.get("attempts", 0) + 1}

    def _parse(self, s: SummaryState) -> SummaryState:
        try:
            return {"summary": parse_summary(s["raw"], s["transcript"]), "error": ""}
        except (ValueError, TypeError, AttributeError) as exc:
            logger.warning("JSON do resumo inválido (tentativa %d): %s", s["attempts"], exc)
            return {"summary": None, "error": str(exc)[:200]}


def _dicts(value) -> list[dict]:
    return [v for v in value or [] if isinstance(v, dict)] if isinstance(value, list) else []


def parse_summary(raw: str, transcript: str) -> Summary:
    """JSON do modelo → Summary, aplicando o contrato: status de decisão válido e
    responsável só quando aparece na reunião. ValueError se não for JSON utilizável."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1].removeprefix("json").strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        data = json.loads(cleaned + "}")  # modelo local às vezes corta a chave final
    if not isinstance(data, dict):
        raise ValueError("o JSON não é um objeto")
    return Summary(
        contributions=[{"speaker": str(c["speaker"]).strip(), "points": [str(p) for p in c.get("points") or []][:5]}
                       for c in _dicts(data.get("contributions")) if str(c.get("speaker") or "").strip()
                       and str(c["speaker"]).strip().lower() in transcript.lower()],  # só quem está na reunião
        topic_decisions=[{"topic": str(t["topic"]), "decision": str(t["decision"]), "effect": str(t.get("effect") or "")}
                         for t in _dicts(data.get("topic_decisions")) if t.get("topic") and t.get("decision")],
        open_questions=[str(q).strip() for q in data.get("open_questions") or [] if str(q).strip()],
        overview=str(data.get("overview") or ""),
        topics=[str(t) for t in data.get("topics") or []],
        tasks=[
            Task(description=t["description"].strip(),
                 responsible=responsible_or_undefined(t.get("responsible") or "", transcript),
                 deadline=t.get("deadline") or "Não definido")
            for t in data.get("tasks") or [] if isinstance(t, dict) and (t.get("description") or "").strip()
        ],
        decisions=[
            Decision(description=d["description"].strip(), context=d.get("context") or "",
                     status=decision_status(d.get("status") or ""))
            for d in data.get("decisions") or [] if isinstance(d, dict) and (d.get("description") or "").strip()
        ],
    )
