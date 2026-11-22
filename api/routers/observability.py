"""Observabilidade centralizada: métricas, logs de todos os serviços e o estado do sistema.

Só para o administrador (ou a chave de serviço, para Prometheus e scripts).
"""
import os
import shutil
import time
from collections import defaultdict

import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse

from api.security import Principal, current_principal
from config.settings import get_settings
from infrastructure import observability as obs
from presentation.container import get_container

router = APIRouter()
QUEUES = ("transcribe", "llm", "bot")


def require_admin(principal: Principal = Depends(current_principal)) -> Principal:
    if principal.user is not None and not principal.user.is_admin:
        raise HTTPException(403, "Só o administrador vê a observabilidade")
    return principal


def queue_depths() -> dict[str, int]:
    """Tarefas esperando em cada fila, somando os níveis de prioridade (fila:1 … fila:9)."""
    r = obs._client()
    if r is None:
        return {}
    try:
        return {q: sum(r.llen(k) for k in [q, *(f"{q}:{p}" for p in range(1, 10))]) for q in QUEUES}
    except Exception:
        return {}


def _ollama() -> dict:
    s = get_settings()
    if s.llm_provider != "ollama" and s.openai_api_key:
        return {"provider": s.llm_provider, "status": "externo"}
    base = s.ollama_base_url.rstrip("/").removesuffix("/v1")
    t0 = time.monotonic()
    try:
        models = [m["name"] for m in requests.get(f"{base}/api/tags", timeout=2).json().get("models", [])]
        return {"provider": "ollama", "status": "ok" if s.ollama_model in models else "sem o modelo",
                "model": s.ollama_model, "latency_ms": round((time.monotonic() - t0) * 1000)}
    except Exception as exc:
        return {"provider": "ollama", "status": f"erro: {type(exc).__name__}", "model": s.ollama_model}


def _calendar(container) -> str:
    if container.calendar is None:
        return "desligada"
    _, error = container.upcoming_events(1)
    return f"erro: {error[:120]}" if error else "ok"


def _latencies() -> dict[str, dict]:
    out = {}
    for key, values in obs.samples().items():
        out[key] = {"count": len(values), "p50": round(obs.percentile(values, 50), 3),
                    "p95": round(obs.percentile(values, 95), 3), "max": round(max(values), 3)}
    return out


def _agent_memory(counters: dict[str, float], latencies: dict[str, dict]) -> dict:
    """Caminho das respostas do chat (ADR-022, S14-4): cache (CAG), quente (trechos na memória) ou
    banco (índice lido do disco ou refeito). Taxa de acerto do cache e p50/p95 por caminho."""
    answers = _totals(counters, "chat_answers_total", "path")
    total = sum(answers.values())
    return {
        "answers_by_path": answers,
        "cache_hit_rate": round(answers.get("cache", 0) / total, 3) if total else None,
        "latency_by_path": {p: latencies[f"chat_seconds|path={p}"] for p in ("cache", "quente", "banco")
                            if f"chat_seconds|path={p}" in latencies},
    }


def _totals(counters: dict[str, float], name: str, by: str) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    for key, value in counters.items():
        metric, labels = obs.parse_key(key)
        if metric == name and "#" not in key:
            out[labels.get(by, "-")] += value
    return dict(out)


@router.get("/summary", summary="Estado do sistema num só lugar")
def summary(_: Principal = Depends(require_admin)):
    """Saúde das dependências, filas, workers, reuniões, usuários, bot, LLM, latências (p50/p95
    das últimas amostras), erros, e-mails e documentos. Pensado para um painel."""
    from api.main import _workers
    container = get_container()
    counters = obs.counters()
    http_by_status = defaultdict(float)
    for key, value in counters.items():
        metric, labels = obs.parse_key(key)
        if metric == "http_requests_total":
            http_by_status[labels.get("status", "?")[0] + "xx"] += value
    audio_dir = get_settings().audio_storage_path
    disk = shutil.disk_usage(audio_dir if os.path.isdir(audio_dir) else ".")
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "workers": _workers(),
        "worker_details": obs.workers() or {},
        "queues": queue_depths(),
        "meetings_by_status": container.repository.count_by_status(),
        "accounts": container.auth.counts() if container.auth else {},
        "bot": container.bot_status(),
        "llm": _ollama(),
        "calendar": _calendar(container),
        "http": dict(http_by_status),
        "pipeline": _totals(counters, "pipeline_stage_total", "result"),
        "pipeline_by_stage": {s: _totals({k: v for k, v in counters.items() if f"stage={s}" in k},
                                         "pipeline_stage_total", "result") for s in ("transcribe", "summarize")},
        "bot_meetings": _totals(counters, "bot_meetings_total", "result"),
        "emails": _totals(counters, "emails_total", "kind"),
        "email_errors": {k: v for k, v in _totals({k: v for k, v in counters.items() if "result=error" in k},
                                                   "emails_total", "kind").items()},
        "documents": _totals(counters, "documents_total", "format"),
        "llm_errors": _totals(counters, "llm_errors_total", "kind"),
        "latencies_seconds": (latencies := _latencies()),
        "agent_memory": _agent_memory(counters, latencies),
        "disk": {"free_gb": round(disk.free / 1e9, 1), "used_pct": round(disk.used / disk.total * 100, 1)},
    }


@router.get("/metrics", response_class=PlainTextResponse, summary="Métricas no formato Prometheus")
def metrics(_: Principal = Depends(require_admin)):
    """Para o Prometheus raspar (com o cabeçalho X-API-Key). Contadores, resumos de duração
    (quantis 0.5/0.95 das últimas amostras) e medidores: filas, reuniões por status, workers."""
    lines = []

    def label_text(labels: dict) -> str:
        if not labels:
            return ""
        return "{" + ",".join(f'{k}="{str(v).replace(chr(34), "")}"' for k, v in sorted(labels.items())) + "}"

    seen_types = set()

    def emit(name: str, kind: str, labels: dict, value: float) -> None:
        full = f"meet_agent_{name}"
        if full not in seen_types:
            lines.append(f"# TYPE {full} {kind}")
            seen_types.add(full)
        lines.append(f"{full}{label_text(labels)} {value:g}")

    counters = obs.counters()
    for key, value in sorted(counters.items()):
        base, _, part = key.partition("#")
        name, labels = obs.parse_key(base)
        if part:  # _count / _sum de um resumo
            emit(f"{name}_{part}", "untyped", labels, value)
        else:
            emit(name, "counter", labels, value)
    for key, values in sorted(obs.samples().items()):
        name, labels = obs.parse_key(key)
        for q in (0.5, 0.95):
            emit(name, "summary", {**labels, "quantile": q}, obs.percentile(values, q * 100))
    for queue, depth in queue_depths().items():
        emit("queue_depth", "gauge", {"queue": queue}, depth)
    for status, n in get_container().repository.count_by_status().items():
        emit("meetings", "gauge", {"status": status}, n)
    from api.main import _workers
    for queue, state in _workers().items():
        emit("worker_up", "gauge", {"queue": queue}, 1 if state == "ok" else 0)
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@router.get("/logs", summary="Logs de todos os serviços")
def logs(meeting_id: str = "", service: str = Query("", description="api, worker-transcribe, worker-llm, bot"),
         level: str = Query("", description="nível mínimo: INFO, WARNING, ERROR"),
         q: str = Query("", description="texto contido na mensagem"),
         limit: int = Query(200, ge=1, le=2000), _: Principal = Depends(require_admin)):
    """Mais recentes primeiro, entre as últimas 5.000 linhas (o stream guarda 50.000)."""
    return obs.logs(limit=limit, meeting_id=meeting_id, service=service, level=level, text=q)


@router.get("/meetings/{meeting_id}", summary="Linha do tempo de uma reunião")
def meeting_timeline(meeting_id: str, _: Principal = Depends(require_admin)):
    """Status, erro, medições do processamento, fila e os logs da reunião em todos os serviços,
    do mais antigo ao mais novo. É por onde começar quando uma reunião deu errado."""
    meeting = get_container().repository.find_by_id(meeting_id)
    if meeting is None:
        raise HTTPException(404, "Reunião não encontrada")
    return {
        "meeting_id": meeting.id, "title": meeting.title, "status": meeting.status.value, "error": meeting.error,
        "platform": meeting.platform, "started_at": meeting.started_at, "duration_minutes": meeting.duration_minutes,
        "metrics": meeting.metrics, "queue": meeting.queue, "queue_position": get_container().queue_position(meeting),
        "logs": list(reversed(obs.logs(limit=2000, meeting_id=meeting_id, scan=50_000))),
    }
