import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from domain.entities.meeting import Meeting, Task
from domain.interfaces.llm_service import ChatReply, ILLMService, LLMServiceError
from use_cases.contract_checks import FALLBACK
from use_cases.llm_context import select_relevant
from use_cases.meeting_memory import MAX_CHARS as MEMORY_CHARS, MAX_NOTES, build_memory, new_note

logger = logging.getLogger(__name__)
_WANTS_ATTACHMENT = re.compile(r"anex|attach|em arquivo|\bpdf\b|\bword\b|docx|xlsx|excel|planilha|csv", re.IGNORECASE)
_EMAIL = re.compile(r"[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+")
DOCUMENT_FORMATS = ("pdf", "docx", "xlsx", "csv", "html", "md")
_FORMAT_ALIASES = {"word": "docx", "doc": "docx", "markdown": "md", "excel": "xlsx", "xls": "xlsx",
                   "planilha": "xlsx", "htm": "html", "dashboard": "html", "web": "html"}

# Quantas mensagens anteriores acompanham a pergunta (40 perguntas e respostas). O agente corta
# pelo orçamento da janela e resume o que sobrar (memória curta, S13-4).
HISTORY_TURNS = 80
# Em reunião longa, quanto de transcrição acompanha a pergunta. Poucos trechos
# bem escolhidos respondem melhor (e mais rápido) que a janela cheia: com ela
# cheia o modelo local deixou passar um dado que estava no meio do contexto.
EXCERPT_CHARS = 8000
# Trechos de outras reuniões que entram sozinhos; a ferramenta search_meetings traz até SEARCH_CHARS.
CROSS_CHARS = 2500
SEARCH_CHARS = 5000


@dataclass
class ChatWithMeetingInput:
    meeting: Meeting
    question: str
    # None = usa a conversa guardada na reunião.
    history: list[dict] | None = None
    # Recebe o texto aos pedaços enquanto o modelo escreve (S16-2). A resposta final pode diferir:
    # se a verificação do contrato reprovar, vale a corrigida, devolvida em `answer`.
    on_delta: Optional[Callable[[str], None]] = None


@dataclass
class ChatWithMeetingOutput:
    answer: str
    success: bool
    error_message: str = ""
    extracted_tasks: list[Task] = field(default_factory=list)
    # Ação que o agente preparou (e-mail a confirmar ou documento gerado); também fica na
    # mensagem do assistente em chat_history["action"].
    action: Optional[dict] = None
    path: str = ""          # caminho da resposta (S14-4): cache, quente ou banco
    searched: bool = False  # o agente usou search_meetings


class ChatWithMeetingUC:
    """Conversa sobre a reunião. Com repositório, a conversa fica guardada na
    reunião. Transcrição longa demais vai ao LLM como resumo + trechos
    relevantes à pergunta (ADR-010)."""

    def __init__(self, llm_service: ILLMService, repository=None, max_context_chars: int = 30000,
                 documents_dir: Optional[Path] = None,
                 write_document: Optional[Callable[..., Path]] = None, memory_store=None, indexer=None,
                 agent_cache=None, metrics: Optional[Callable[[str, float], None]] = None,
                 window_chars: int = 0) -> None:
        # Tetos dos blocos pela janela do modelo (ContextBudget, S12-5/S16-1): no modelo piso (32k) ficam
        # nos valores fixos de sempre; numa janela menor encolhem na mesma proporção, sem estourar.
        def cap(fixed: int, share: float) -> int:
            return min(fixed, int(window_chars * share)) if window_chars else fixed
        self._excerpt_chars, self._cross_chars = cap(EXCERPT_CHARS, 0.2), cap(CROSS_CHARS, 0.08)
        self._search_chars, self._records_chars = cap(SEARCH_CHARS, 0.12), cap(MEMORY_CHARS, 0.06)
        self._indexer = indexer  # busca híbrida nos trechos (S13-3); sem ele, busca por palavra
        self._cache = agent_cache  # CAG (S14-3): resposta já dada à mesma pergunta
        self._metrics = metrics or (lambda path, seconds: None)
        self._memory = memory_store  # notas do remember; sem ele, sem memória entre reuniões
        self._llm = llm_service
        self._repo = repository
        self._max_chars = max_context_chars
        self._documents_dir = documents_dir
        self._write_document = write_document

    def execute(self, input_data: ChatWithMeetingInput) -> ChatWithMeetingOutput:
        meeting = input_data.meeting

        if not meeting.is_transcribed:
            return ChatWithMeetingOutput(
                answer="",
                success=False,
                error_message="Não há transcrição disponível para esta reunião.",
            )

        history = meeting.chat_history if input_data.history is None else input_data.history
        question, t0 = input_data.question, time.monotonic()
        previous = next((m["content"] for m in reversed(history) if m.get("role") == "user"), "")
        # Roteador (S14-4): resposta em cache → trechos quentes na memória → índice no disco (RAG).
        cached = self._cache.get(meeting.owner_id, meeting.id, previous, question) if self._cache else None
        if cached is not None:
            self._save_turn(meeting, question, cached, None)
            self._metrics("cache", time.monotonic() - t0)
            return ChatWithMeetingOutput(answer=cached, success=True, path="cache")
        loads = self._indexer.store.disk_loads if self._indexer else 0
        context, question_context = self._context(meeting, question)
        llm_history = [_for_llm(m) for m in history[-HISTORY_TURNS:]]
        can_search = self._indexer is not None and self._repo is not None
        searched = False
        stream = {"on_delta": input_data.on_delta} if input_data.on_delta else {}
        try:
            reply = self._llm.chat(question=question, context=context, history=llm_history,
                                   question_context=question_context, **({"can_search": True} if can_search else {}),
                                   **stream)
            if isinstance(reply, ChatReply) and (reply.tool or {}).get("name") == "search_meetings":
                searched = True  # S14-2: o agente pediu para aprofundar; responde de novo com o que voltar
                query = str((reply.tool.get("arguments") or {}).get("query") or question)
                found = self._search_others(meeting, query, self._search_chars)
                question_context += (f"RESULTADO DA BUSCA EM OUTRAS REUNIÕES (search_meetings: \"{query}\"):\n"
                                     f"{found or 'Nenhum trecho encontrado nas outras reuniões deste usuário.'}\n\n")
                reply = self._llm.chat(question=question, context=context, history=llm_history,
                                       question_context=question_context, **stream)
        except LLMServiceError as e:
            return ChatWithMeetingOutput(answer="", success=False, error_message=str(e))
        if isinstance(reply, str):  # implementações da porta que não usam ferramentas
            reply = ChatReply(reply)
        path = "banco" if self._indexer and self._indexer.store.disk_loads != loads else "quente"

        answer, action = reply.answer, None
        if (reply.tool or {}).get("name") == "search_meetings":  # pediu de novo: não insiste
            reply = ChatReply(reply.answer or "Não encontrei isso nas suas outras reuniões.")
            answer = reply.answer
        if reply.tool:
            user_texts = [input_data.question, *(m["content"] for m in history if m.get("role") == "user")]
            try:
                answer, action = self._prepare_action(meeting, reply.tool, user_texts)
            except Exception as e:  # documento que não deu para gerar: diz o motivo, não derruba o chat
                answer = f"Não consegui preparar isso: {e}"

        self._save_turn(meeting, question, answer, action)
        if self._cache and not reply.tool and answer and answer != FALLBACK:  # ação e recusa não se repetem
            self._cache.put(meeting.owner_id, meeting.id, previous, question, answer)
        self._metrics(path, time.monotonic() - t0)
        return ChatWithMeetingOutput(answer=answer, success=True, action=action, path=path, searched=searched)

    def _save_turn(self, meeting: Meeting, question: str, answer: str, action: Optional[dict]) -> None:
        if self._repo:
            reply_msg = {"role": "assistant", "content": answer, **({"action": action} if action else {})}
            new = [{"role": "user", "content": question}, reply_msg]
            meeting.chat_history = [*meeting.chat_history, *new]
            # Só a conversa: gravar a reunião inteira devolvia o status e o resumo de quando a
            # pergunta começou, apagando o resumo que terminou enquanto o modelo respondia.
            self._repo.append_chat(meeting.id, new)

    def _prepare_action(self, meeting: Meeting, tool: dict, user_texts: list[str]) -> tuple[str, Optional[dict]]:
        args = tool.get("arguments") or {}
        action_id = uuid.uuid4().hex[:12]

        if tool.get("name") == "send_email":
            to = args.get("to") or []
            to = [to] if isinstance(to, str) else to
            to = list(dict.fromkeys(a.strip() for a in to if _EMAIL.fullmatch(a.strip() or "")))
            typed = " ".join(user_texts).lower()
            # O modelo não escolhe destinatário: só vale endereço que o usuário escreveu.
            if not to or any(a.lower() not in typed for a in to):
                return "Para enviar o e-mail, escreva aqui o endereço de cada destinatário.", None
            subject = str(args.get("subject") or f"Reunião: {meeting.title}")[:200]
            body = str(args.get("body") or "").strip()
            if not body:
                return "Não consegui montar o texto do e-mail. Diga o que ele deve conter.", None
            attachments, problem = self._email_attachments(meeting, args)
            if problem:
                return problem, None
            action = {"id": action_id, "type": "email", "status": "pending", "to": to,
                      "subject": subject, "body": body[:20000], "attachments": attachments}
            # Pediu arquivo mas nada foi anexado: avisa, em vez de parecer que foi.
            note = ""
            if not attachments and _WANTS_ATTACHMENT.search(user_texts[0]):
                note = (" ⚠️ Nenhum arquivo foi anexado: ainda não há documento gerado nesta conversa. "
                        "Peça o documento (ex.: \"gere a ata em PDF\") e depois o envio com anexo.")
            files = f" Anexos: {', '.join(a['filename'] for a in attachments)}." if attachments else ""
            return (f"Preparei o e-mail para {', '.join(to)}.{files} Confira o texto abaixo e confirme o envio; "
                    f"nada é enviado antes disso.{note}"), action

        if tool.get("name") == "create_document":
            if self._documents_dir is None or self._write_document is None:
                return "A geração de documentos não está disponível neste ambiente.", None
            doc, problem = self._make_document(meeting, args, action_id)
            if problem:
                return problem, None
            action = {"id": action_id, "type": "document", "status": "created", **doc}
            return f"Gerei o documento {doc['title']} ({doc['format'].upper()}). Baixe pelo botão abaixo.", action

        if tool.get("name") == "remember":
            if self._memory is None:
                return "A memória entre reuniões não está disponível neste ambiente.", None
            note = new_note(meeting.owner_id, str(args.get("note") or ""), meeting.id)
            if note is None:
                return "Não entendi o que devo lembrar. Pode repetir?", None
            self._memory.add(note)
            return (f"Anotado: {note['text']} Vou levar isso em conta nas suas próximas conversas, em "
                    "qualquer reunião. Você pode ver e apagar as notas em Minha conta."), \
                {"id": note["_id"], "type": "memory", "status": "created", "title": note["text"]}

        return "Não sei executar essa ação.", None

    def _make_document(self, meeting: Meeting, args: dict, doc_id: str) -> tuple[Optional[dict], str]:
        """Gera o arquivo (format, title, content em `args`). Devolve ({format, title, filename}, "")
        ou (None, motivo para mostrar ao usuário)."""
        fmt = str(args.get("format") or "pdf").lower().lstrip(".")
        fmt = _FORMAT_ALIASES.get(fmt, fmt)
        if fmt not in DOCUMENT_FORMATS:
            return None, (f"Formato {fmt} não suportado. Posso gerar PDF, Word (docx), Excel (xlsx), CSV, "
                          "HTML (com gráficos) ou Markdown.")
        title = str(args.get("title") or meeting.title or "Documento da reunião")[:150]
        content = str(args.get("content") or "").strip()
        if not content:
            return None, "Não consegui montar o conteúdo do documento. Diga o que ele deve conter."
        # Dashboard sem nenhuma tabela (o modelo escreveu só prosa): o sistema põe os números
        # que ele mesmo contou, para a página ter gráfico e com o número certo.
        extra = meeting_stats(meeting) if fmt == "html" else []
        self._write_document(document_path(self._documents_dir, meeting.id, doc_id, fmt), fmt, title, content,
                             **({"fallback_tables": extra} if extra else {}))
        slug = re.sub(r"[^\w-]+", "-", title.lower()).strip("-")[:60] or "documento"
        return {"format": fmt, "title": title, "filename": f"{slug}.{fmt}"}, ""

    def _email_attachments(self, meeting: Meeting, args: dict) -> tuple[list[dict], str]:
        """Anexos do e-mail: `attachment` gera um arquivo agora; `attach_documents` junta os que o
        chat já gerou. Cada anexo = {id, format, filename}; o arquivo é lido na hora do envio."""
        found: list[dict] = []
        new = args.get("attachment")
        if isinstance(new, dict) and new:
            if self._documents_dir is None or self._write_document is None:
                return [], "A geração de documentos não está disponível neste ambiente."
            doc_id = uuid.uuid4().hex[:12]
            doc, problem = self._make_document(meeting, new, doc_id)
            if problem:
                return [], problem
            found.append({"id": doc_id, "format": doc["format"], "filename": doc["filename"]})
        if args.get("attach_documents") and self._documents_dir is not None:
            for msg in meeting.chat_history:
                a = msg.get("action") or {}
                if a.get("type") == "document" and document_path(
                        self._documents_dir, meeting.id, a["id"], a.get("format", "")).exists():
                    found.append({"id": a["id"], "format": a["format"], "filename": a["filename"]})
        return found, ""

    def _context(self, meeting: Meeting, question: str) -> tuple[str, str]:
        """(o que vale para a conversa toda, o que foi buscado para esta pergunta). O primeiro fica
        igual entre perguntas da mesma reunião: é o prefixo que o Ollama reaproveita (S12-5)."""
        # A reunião aberta diz o próprio título e data: sem isso, com registros de outras reuniões
        # no contexto, o modelo trocou "esta reunião" pela anterior (teste de 2026-11-15).
        opened = (f"REUNIÃO ABERTA (é sobre esta que o usuário pergunta): \"{meeting.title}\", "
                  f"{meeting.started_at:%d/%m/%Y}\n\n")
        stable, excerpts = self._meeting_context(meeting, question)
        intent = classify_intent(question)
        hint = f"TIPO DE PERGUNTA (classificado pelo sistema): {intent}. {INTENT_HINTS[intent]}\n\n"
        return self._notes_block(meeting) + opened + stable, \
            excerpts + self._memory_block(meeting, question, intent) + hint

    def _notes_block(self, meeting: Meeting) -> str:
        """Memória procedural (S15-1): preferências, glossário e contexto que o usuário pediu para
        lembrar. Fica no prefixo estável (muda só quando ele grava ou apaga uma nota)."""
        if self._memory is None:
            return ""
        notes = self._memory.list(meeting.owner_id)[-MAX_NOTES:]
        if not notes:
            return ""
        return ("PREFERÊNCIAS, GLOSSÁRIO E CONTEXTO QUE O USUÁRIO PEDIU PARA VOCÊ LEMBRAR (memória procedural, "
                "§14; valem para todas as reuniões dele; siga as preferências de formato):\n"
                + "\n".join(f"- {n['text']}" for n in notes) + "\n\n")

    def _others(self, meeting: Meeting) -> list[Meeting]:
        """Outras reuniões do MESMO dono (o repositório filtra): é o limite de tudo que vem de fora."""
        return [m for m in self._repo.list_all(meeting.owner_id)
                if m.id != meeting.id and not m.source_id and m.owner_id == meeting.owner_id]

    def _search_others(self, meeting: Meeting, question: str, max_chars: int) -> str:
        if self._indexer is None or self._repo is None:
            return ""
        try:
            related = self._indexer.entities.related_meetings(meeting, question)
            return self._indexer.chunks.search_many(self._others(meeting), question, max_chars, related)
        except Exception:
            logger.exception("[%s] busca entre reuniões falhou", meeting.id)
            return ""

    def _memory_block(self, meeting: Meeting, question: str, intent: str = "fato") -> str:
        """§14: registros das outras reuniões do mesmo dono e falas delas ligadas à pergunta (S14-1).
        As notas do usuário vão no prefixo estável (_notes_block)."""
        if self._memory is None or self._repo is None:
            return ""
        block = build_memory(meeting, self._others(meeting), [], question, self._records_chars)
        found = self._search_others(meeting, question, self._cross_chars * (2 if intent == "entre reuniões" else 1))
        if found:
            block += ("FALAS DE OUTRAS REUNIÕES DO MESMO USUÁRIO LIGADAS A ESTA PERGUNTA (§14, §20). São literais; "
                      "cada linha já traz [Título · data · horário]: ao usar uma, cite nesse formato.\n"
                      f"{found}\n\n")
        return block

    def _meeting_context(self, meeting: Meeting, question: str) -> tuple[str, str]:
        full = meeting.transcript_for_llm
        if len(full) <= self._max_chars:
            return _stats_block(meeting) + _decisions_block(meeting) + full, ""
        summary = meeting.summary.formatted if meeting.summary else ""
        excerpts = self._excerpts(meeting, question, min(self._excerpt_chars, self._max_chars))
        stable = (
            f"{meeting.participants_header}"
            f"{_stats_block(meeting)}"
            f"RESUMO DA REUNIÃO:\n{summary}\n\n"
            "A reunião é longa: junto com cada pergunta vêm só os trechos da transcrição mais ligados a ela. "
            "Se a resposta não estiver neles nem no resumo, diga que não encontrou nos trechos consultados."
        )
        return stable, f"TRECHOS DA TRANSCRIÇÃO LIGADOS A ESTA PERGUNTA:\n{excerpts}\n\n"


    def _excerpts(self, meeting: Meeting, question: str, max_chars: int) -> str:
        if self._indexer is not None:
            try:
                return self._indexer.chunks.search(meeting, question, max_chars)
            except Exception:
                logger.exception("[%s] busca nos trechos falhou; usando a busca por palavra", meeting.id)
        return select_relevant(meeting.transcript_formatted or meeting.transcript_text, question, max_chars=max_chars)


# Intenção da pergunta (S15-3), sem chamar o modelo: muda quanto se busca e o que se pede na resposta.
_INTENTS = [
    ("pendências", re.compile(r"\b(em aberto|pendent|pend[êe]ncia|falta(m)? (definir|decidir)|ficou para|"
                              r"pr[óo]ximos passos|o que falta|sem respons[áa]vel|n[ãa]o (foi )?resolvid)", re.I)),
    ("entre reuniões", re.compile(r"\b(outras? reuni|reuni[õo]es anteriores|reuni[ãa]o anterior|[úu]ltima reuni|"
                                  r"antes|desde|hist[óo]ric|evolu|mudou|continua valendo|ainda vale|"
                                  r"nas minhas reuni)", re.I)),
    ("análise", re.compile(r"\b(o que (voc[êe] )?achou|avalia|an[áa]lise|opini[ãa]o|melhorar|pontos fortes|"
                           r"riscos?\b|recomenda)", re.I)),
]
INTENT_HINTS = {
    "fato": "Responda direto, com a evidência (§19).",
    "pendências": ("Liste o que ficou em aberto com o estado de cada item e termine com \"Perguntas para você\" "
                   "(no máximo três, só as que mudam decisão, prazo ou responsável; §10.1)."),
    "entre reuniões": ("Use as falas e registros de outras reuniões, citando [Título · data · horário] de cada "
                       "uma (§20); a versão mais recente vale (§14)."),
    "análise": "Siga o §11: o que funcionou, o que precisa melhorar, riscos e recomendações, com evidências.",
}


def classify_intent(question: str) -> str:
    return next((name for name, pattern in _INTENTS if pattern.search(question)), "fato")


_SPEAKER_LINE = re.compile(r"^\[\d{1,2}:\d{2}(?::\d{2})?\]\s*([^:\]\n]{1,60}):", re.MULTILINE)


def meeting_stats(meeting: Meeting) -> list[tuple[str, list[list[str]]]]:
    """Contagens calculadas pelo sistema, como tabelas (título, linhas com cabeçalho).
    Modelo de linguagem conta mal: num teste, "falas por participante" saiu 3/2/1 com 6/4/3."""
    tables = []
    counts: dict[str, int] = {}
    for name in _SPEAKER_LINE.findall(meeting.transcript_formatted or ""):
        counts[name.strip()] = counts.get(name.strip(), 0) + 1
    if counts:
        tables.append(("Falas por participante", [["Participante", "Falas"],
                       *([n, str(c)] for n, c in sorted(counts.items(), key=lambda kv: -kv[1]))]))
    tasks = meeting.summary.tasks if meeting.summary else []
    if tasks:
        owners: dict[str, int] = {}
        for t in tasks:
            owners[t.responsible] = owners.get(t.responsible, 0) + 1
        tables.append(("Tarefas por responsável", [["Responsável", "Tarefas"], *([n, str(c)] for n, c in owners.items())]))
    decisions = meeting.summary.decisions if meeting.summary else []
    if decisions:
        by_status: dict[str, int] = {}
        for d in decisions:
            by_status[d.status or "sem estado"] = by_status.get(d.status or "sem estado", 0) + 1
        tables.append(("Decisões por estado", [["Estado", "Decisões"], *([k, str(v)] for k, v in by_status.items())]))
    return tables


def _stats_block(meeting: Meeting) -> str:
    lines = [f"{title.lower()}: " + ", ".join(f"{r[0]} {r[1]}" for r in rows[1:]) for title, rows in meeting_stats(meeting)]
    if meeting.duration_minutes:
        lines.append(f"duração: {meeting.duration_minutes:.0f} min")
    if not lines:
        return ""
    return ("NÚMEROS DA REUNIÃO (contados pelo sistema; use estes em tabelas e gráficos, não conte de novo):\n"
            + "\n".join(f"- {l}" for l in lines) + "\n\n")


def _decisions_block(meeting: Meeting) -> str:
    """Estado de cada decisão, como o resumo classificou (§7 do contrato): o chat
    responde "o que foi aprovado" com a mesma classificação do resumo."""
    decisions = [d for d in (meeting.summary.decisions if meeting.summary else []) if d.status]
    if not decisions:
        return ""
    lines = "\n".join(f"- [{d.status}] {d.description}" for d in decisions)
    return f"DECISÕES REGISTRADAS NO RESUMO (estado de cada uma; confira na transcrição):\n{lines}\n\n"


def document_path(documents_dir: Path, meeting_id: str, action_id: str, fmt: str) -> Path:
    """Onde fica o arquivo de um documento gerado no chat. Montado só com ids do sistema,
    nunca com texto do modelo ou do usuário."""
    return Path(documents_dir) / meeting_id / f"{action_id}.{fmt}"


def _for_llm(message: dict) -> dict:
    """Mensagem da conversa como o modelo a vê. A confirmação de uma ação vira uma nota do
    sistema: com o texto "Gerei o documento…" no histórico, o modelo passou a responder assim
    sem chamar a ferramenta (nenhum arquivo era gerado)."""
    action = message.get("action")
    if message["role"] != "assistant" or not action:
        return {"role": message["role"], "content": message["content"]}
    tool = {"document": "create_document", "email": "send_email", "memory": "remember"}.get(action["type"], "?")
    return {"role": "assistant", "content": f"[O sistema executou a ferramenta {tool} para o pedido acima.]"}
