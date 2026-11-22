"""Observabilidade centralizada no Redis (que todos os serviços já usam).

- Logs: cada processo (api, workers, bot) manda as linhas para o stream
  `obs:logs` (últimas LOG_MAXLEN), com serviço, nível, reunião e mensagem.
- Métricas: contadores em `obs:counters` (hash) e amostras de duração em listas
  `obs:samples:<nome>` (últimas SAMPLE_MAXLEN), somadas entre todos os processos.

Tudo aqui é melhor-esforço: Redis fora desliga a telemetria, nunca derruba quem mede.
Em solo (sem Redis) as funções não fazem nada.
"""
from __future__ import annotations

import json
import logging
import os
import time
from functools import lru_cache
from typing import Optional

LOG_MAXLEN = 50_000
SAMPLE_MAXLEN = 2_000
_COUNTERS = "obs:counters"
_LOGS = "obs:logs"
_SAMPLES = "obs:samples:"

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _redis():
    from config.settings import get_settings
    settings = get_settings()
    if not settings.is_collab:
        return None
    import redis
    return redis.Redis.from_url(settings.redis_url, socket_timeout=1, socket_connect_timeout=1)


_down_until = 0.0


def _client():
    """Redis, ou None se desligado ou fora há pouco (evita travar cada chamada por 1 s)."""
    global _down_until
    if time.monotonic() < _down_until:
        return None
    try:
        return _redis()
    except Exception:
        return None


def _failed(exc: Exception) -> None:
    global _down_until
    _down_until = time.monotonic() + 30


def _key(name: str, labels: Optional[dict]) -> str:
    if not labels:
        return name
    return name + "|" + ",".join(f"{k}={labels[k]}" for k in sorted(labels))


def parse_key(key: str) -> tuple[str, dict]:
    name, _, rest = key.partition("|")
    return name, dict(p.split("=", 1) for p in rest.split(",") if "=" in p) if rest else {}


def incr(name: str, labels: Optional[dict] = None, by: int = 1) -> None:
    r = _client()
    if r is None:
        return
    try:
        r.hincrby(_COUNTERS, _key(name, labels), by)
    except Exception as exc:
        _failed(exc)


def observe(name: str, seconds: float, labels: Optional[dict] = None) -> None:
    """Uma duração (ou outro valor): guarda a amostra e soma contagem e total."""
    r = _client()
    if r is None:
        return
    key = _key(name, labels)
    try:
        pipe = r.pipeline()
        pipe.lpush(_SAMPLES + key, round(seconds, 4))
        pipe.ltrim(_SAMPLES + key, 0, SAMPLE_MAXLEN - 1)
        pipe.hincrby(_COUNTERS, key + "#count", 1)
        pipe.hincrbyfloat(_COUNTERS, key + "#sum", seconds)
        pipe.execute()
    except Exception as exc:
        _failed(exc)


class timed:
    """with timed("llm_seconds", {"kind": "chat"}): ...  — registra a duração e, se der erro,
    conta em <nome sem _seconds>_errors_total."""

    def __init__(self, name: str, labels: Optional[dict] = None) -> None:
        self.name, self.labels = name, labels

    def __enter__(self):
        self.t0 = time.monotonic()
        return self

    def __exit__(self, exc_type, *_):
        observe(self.name, time.monotonic() - self.t0, self.labels)
        if exc_type is not None:
            incr(self.name.removesuffix("_seconds") + "_errors_total", self.labels)
        return False


# ── Workers vivos (batimento) ─────────────────────────────────────────
# Perguntar ao Celery quem está vivo (inspect) não serve: um worker de pool solo ocupado com uma
# transcrição longa não responde, e o /health dizia "sem worker" durante todo trabalho normal.
# Cada worker grava um batimento a cada HEARTBEAT_S numa thread própria; sem batimento por
# HEARTBEAT_TTL, o worker é dado como morto.

HEARTBEAT_S = 10
HEARTBEAT_TTL = 30
_WORKER = "obs:worker:"


def heartbeat(queues: list[str], host: str, current: Optional[dict] = None) -> None:
    r = _client()
    if r is None:
        return
    value = json.dumps({"host": host, "ts": time.time(), "task": current or None})
    try:
        pipe = r.pipeline()
        for q in queues:
            pipe.set(f"{_WORKER}{q}:{host}", value, ex=HEARTBEAT_TTL)
        pipe.execute()
    except Exception as exc:
        _failed(exc)


def workers() -> Optional[dict[str, list[dict]]]:
    """{fila: [{host, ts, task}]} dos workers com batimento recente; None se não deu para ler."""
    r = _client()
    if r is None:
        return None
    try:
        out: dict[str, list[dict]] = {}
        for key in r.scan_iter(match=_WORKER + "*", count=200):
            queue = key.decode()[len(_WORKER):].split(":", 1)[0]
            raw = r.get(key)
            if raw:
                out.setdefault(queue, []).append(json.loads(raw))
        return out
    except Exception as exc:
        _failed(exc)
        return None


# ── Leitura (API de observabilidade) ──────────────────────────────────

def counters() -> dict[str, float]:
    r = _client()
    if r is None:
        return {}
    return {k.decode(): float(v) for k, v in r.hgetall(_COUNTERS).items()}


def samples() -> dict[str, list[float]]:
    r = _client()
    if r is None:
        return {}
    out = {}
    for key in r.scan_iter(match=_SAMPLES + "*", count=500):
        out[key.decode()[len(_SAMPLES):]] = [float(v) for v in r.lrange(key, 0, -1)]
    return out


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    return values[min(len(values) - 1, int(round(p / 100 * (len(values) - 1))))]


def logs(limit: int = 200, meeting_id: str = "", service: str = "", level: str = "", text: str = "",
         scan: int = 5000) -> list[dict]:
    """Mais recentes primeiro. Filtra entre as últimas `scan` linhas."""
    r = _client()
    if r is None:
        return []
    order = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    min_level = order.index(level.upper()) if level.upper() in order else 0
    out = []
    for entry_id, fields in r.xrevrange(_LOGS, count=scan):
        rec = {k.decode(): v.decode(errors="replace") for k, v in fields.items()}
        if meeting_id and rec.get("meeting_id") != meeting_id:
            continue
        if service and rec.get("service") != service:
            continue
        if rec.get("level") in order and order.index(rec["level"]) < min_level:
            continue
        if text and text.lower() not in rec.get("message", "").lower():
            continue
        rec["id"] = entry_id.decode()
        out.append(rec)
        if len(out) >= limit:
            break
    return out


# ── Handler de log ────────────────────────────────────────────────────

class RedisLogHandler(logging.Handler):
    """Manda cada linha de log para o stream central. Nunca levanta exceção."""

    def __init__(self, service: str, level: int = logging.INFO) -> None:
        super().__init__(level)
        self.service = service

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(("redis", __name__)):
            return  # o próprio envio não gera log (evita laço)
        r = _client()
        if r is None:
            return
        try:
            message = record.getMessage()
            if record.exc_info:
                message += "\n" + self.formatException(record.exc_info)
            r.xadd(_LOGS, {
                "ts": f"{record.created:.3f}", "service": self.service, "level": record.levelname,
                "meeting_id": getattr(record, "meeting_id", "-"), "logger": record.name,
                "message": message[:4000], "host": os.environ.get("HOSTNAME", ""),
            }, maxlen=LOG_MAXLEN, approximate=True)
        except Exception as exc:
            _failed(exc)
