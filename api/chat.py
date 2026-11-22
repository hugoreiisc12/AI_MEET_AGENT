import json
import logging
import queue
import threading

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from api.schemas.meeting import ChatActionSchema, ChatRequest, ChatResponse
from api.security import Principal, current_principal, rate_limited
from config.settings import get_settings
from presentation.container import get_container
from use_cases.chat_with_meeting import ChatWithMeetingInput

logger = logging.getLogger(__name__)
router = APIRouter()
# Chamadas de chat ao LLM ao mesmo tempo, por processo da API (ADR-015). O excedente
# espera uma vaga; o total entre processos é API_WORKERS × CHAT_MAX_CONCURRENT.
_llm_slots = threading.BoundedSemaphore(get_settings().chat_max_concurrent)
_WAIT_S = 60  # cada espera ocupa uma thread do pool da API (40 por processo)


@router.post("/{meeting_id}/chat", response_model=ChatResponse, summary="Pergunta sobre a reunião", responses={
    404: {"description": "Reunião não existe ou é de outro usuário"},
    422: {"description": "Reunião ainda não foi transcrita"},
    429: {"description": "Acima de RATE_LIMIT_PER_MINUTE pedidos por minuto (cabeçalho Retry-After)"},
    503: {"description": "O LLM está ocupado com outras perguntas; tente de novo"},
})
def chat(meeting_id: str, body: ChatRequest, principal: Principal = Depends(rate_limited)):
    """A pergunta e a resposta entram em `chat_history` da reunião (GET /meetings/{id}).

    Pedidos de ação viram `action` na resposta: "mande isso para ana@empresa.com" prepara um
    e-mail (só para endereços escritos pelo usuário) que espera POST .../actions/{id}/send;
    "gere um PDF/Word da ata" gera o arquivo, baixado em GET .../actions/{id}/document."""
    container = get_container()
    meeting = container.meeting_for(meeting_id, principal.owner_id)

    if not meeting:
        raise HTTPException(404, "Reunião não encontrada")
    if not meeting.is_transcribed:
        raise HTTPException(422, "Reunião ainda não foi transcrita")

    history = None if body.history is None else [m.model_dump() for m in body.history]
    if not _llm_slots.acquire(timeout=_WAIT_S):
        raise HTTPException(503, "O assistente está ocupado com outras perguntas. Tente de novo em instantes.",
                            headers={"Retry-After": "30"})
    try:
        result = container.chat_with_meeting.execute(
            ChatWithMeetingInput(meeting=meeting, question=body.question, history=history)
        )
    finally:
        _llm_slots.release()
    if not result.success:
        raise HTTPException(500, result.error_message)

    return ChatResponse(answer=result.answer, meeting_id=meeting_id, action=result.action)


@router.post("/{meeting_id}/chat/stream", summary="Pergunta, com a resposta aos pedaços (NDJSON)", responses={
    200: {"content": {"application/x-ndjson": {}}, "description": (
        'Uma linha JSON por evento: {"delta": "texto"} enquanto o modelo escreve; no fim {"done": ChatResponse} '
        '(vale o answer do done: se a verificação do contrato reprovar a primeira versão, ele traz a corrigida) '
        'ou {"error": "mensagem"}.')},
    404: {"description": "Reunião não existe ou é de outro usuário"},
    422: {"description": "Reunião ainda não foi transcrita"},
    429: {"description": "Acima de RATE_LIMIT_PER_MINUTE pedidos por minuto (cabeçalho Retry-After)"},
    503: {"description": "O LLM está ocupado com outras perguntas; tente de novo"},
})
def chat_stream(meeting_id: str, body: ChatRequest, principal: Principal = Depends(rate_limited)):
    """Mesmo que POST /chat, mas as primeiras palavras aparecem em segundos (S16-2)."""
    container = get_container()
    meeting = container.meeting_for(meeting_id, principal.owner_id)
    if not meeting:
        raise HTTPException(404, "Reunião não encontrada")
    if not meeting.is_transcribed:
        raise HTTPException(422, "Reunião ainda não foi transcrita")
    history = None if body.history is None else [m.model_dump() for m in body.history]
    if not _llm_slots.acquire(timeout=_WAIT_S):
        raise HTTPException(503, "O assistente está ocupado com outras perguntas. Tente de novo em instantes.",
                            headers={"Retry-After": "30"})
    events: queue.Queue = queue.Queue()

    def run() -> None:
        try:
            result = container.chat_with_meeting.execute(ChatWithMeetingInput(
                meeting=meeting, question=body.question, history=history,
                on_delta=lambda text: events.put({"delta": text})))
            if result.success:
                done = ChatResponse(answer=result.answer, meeting_id=meeting_id, action=result.action)
                events.put({"done": done.model_dump(mode="json")})
            else:
                events.put({"error": result.error_message})
        except Exception:
            logger.exception("[%s] chat em streaming falhou", meeting_id)
            events.put({"error": "Não foi possível consultar o agente."})
        finally:
            _llm_slots.release()
            events.put(None)

    threading.Thread(target=run, daemon=True).start()

    def lines():
        while (event := events.get()) is not None:
            yield json.dumps(event, ensure_ascii=False) + "\n"
    return StreamingResponse(lines(), media_type="application/x-ndjson")


@router.delete("/{meeting_id}/chat", status_code=204, summary="Limpa a conversa da reunião",
               responses={404: {"description": "Reunião não existe ou é de outro usuário"}})
def clear_chat(meeting_id: str, principal: Principal = Depends(current_principal)):
    """Apaga `chat_history`, os documentos gerados no chat e os e-mails não enviados.
    Resumo, transcrição e tarefas continuam."""
    get_container().clear_chat(_meeting_or_404(meeting_id, principal))


def _meeting_or_404(meeting_id: str, principal: Principal):
    meeting = get_container().meeting_for(meeting_id, principal.owner_id)
    if not meeting:
        raise HTTPException(404, "Reunião não encontrada")
    return meeting


_ACTION_ERRORS = {404: {"description": "Reunião ou ação não encontrada"},
                  409: {"description": "E-mail já enviado ou descartado, ou SMTP indisponível"}}


@router.post("/{meeting_id}/actions/{action_id}/send", response_model=ChatActionSchema, responses=_ACTION_ERRORS,
             summary="Envia o e-mail preparado no chat")
def send_email_action(meeting_id: str, action_id: str, principal: Principal = Depends(rate_limited)):
    return _resolve(meeting_id, action_id, principal, send=True)


@router.post("/{meeting_id}/actions/{action_id}/cancel", response_model=ChatActionSchema, responses=_ACTION_ERRORS,
             summary="Descarta o e-mail preparado no chat")
def cancel_email_action(meeting_id: str, action_id: str, principal: Principal = Depends(rate_limited)):
    return _resolve(meeting_id, action_id, principal, send=False)


def _resolve(meeting_id: str, action_id: str, principal: Principal, send: bool):
    meeting = _meeting_or_404(meeting_id, principal)
    try:
        return get_container().resolve_email_action(meeting, action_id, send)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except (ValueError, RuntimeError) as exc:  # já resolvido, ou SMTP fora: continua pendente
        raise HTTPException(409, str(exc))


_MEDIA = {"pdf": "application/pdf", "md": "text/markdown; charset=utf-8",
          "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          "csv": "text/csv; charset=utf-8", "html": "text/html; charset=utf-8"}


@router.get("/{meeting_id}/actions/{action_id}/document", response_class=FileResponse,
            responses={404: {"description": "Reunião ou documento não encontrado"}},
            summary="Baixa o documento gerado no chat")
def download_document(meeting_id: str, action_id: str, principal: Principal = Depends(current_principal)):
    meeting = _meeting_or_404(meeting_id, principal)
    try:
        path, action = get_container().document_file(meeting, action_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    return FileResponse(path, media_type=_MEDIA.get(action["format"]), filename=action["filename"])
