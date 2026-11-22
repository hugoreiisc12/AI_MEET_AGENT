"""Regras do contrato do agente (SPEC_CONTRACT.md) que dão para conferir sem outro
modelo (ADR-014). Cada função devolve as violações encontradas; vazio = passou.

Não confere significado (proposta tratada como decisão, por exemplo): isso fica
no prompt e na avaliação (scripts/eval_agent.py).
"""
from __future__ import annotations

import re
import unicodedata

_PT = {"de", "que", "não", "foi", "para", "com", "uma", "os", "as", "na", "no", "reunião", "da", "do", "é", "em",
       "se", "por", "mais", "como", "mas", "ao", "pela", "pelo", "são", "está", "sobre"}
_EN = {"the", "and", "was", "were", "is", "of", "to", "meeting", "with", "that", "not", "for", "it", "on", "be",
       "this", "are", "by"}
# §4: fala citada entre aspas precisa estar na transcrição. Citações curtas
# ("sim", "ok") são ignoradas: aparecem como expressão, não como fala.
_QUOTE = re.compile(r"[\"“”«]([^\"“”«»]{12,400})[\"“”»]")
_MIN_QUOTE_WORDS = 4
# §4: "atribuir declarações a pessoas que não as fizeram".
_ATTRIBUTION = re.compile(
    r"\b(?i:segundo|conforme|de acordo com)\s+(?:o |a )?([A-ZÀ-Ý][a-zà-ÿ]+)"
    r"|\b([A-ZÀ-Ý][a-zà-ÿ]+)\s+(?:disse|afirmou|declarou|mencionou|falou|propôs|sugeriu|comentou|explicou)\b"
)
# Linha da transcrição reproduzida na resposta: "[01:45] Bruno: texto".
_LINE = re.compile(r"\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*([^:\]\n]{1,60}):\s*([^\n]+)")
_LINE_WORDS = 5
# §20: fala ou item de outra reunião, "[Título · dd/mm/aaaa · hh:mm] Nome: texto" ou "[Título · dd/mm/aaaa]".
_CROSS = re.compile(r"\[([^\]\n·]{2,120}?)\s*·\s*(\d{2}/\d{2}/\d{4})(?:\s*·\s*(\d{1,2}:\d{2}(?::\d{2})?))?\]"
                    r"(?:\s*([^:\]\n]{1,60}):\s*([^\n]+))?")
_CROSS_HEAD = re.compile(r"^\[([^\]\n·]+?) · \d{2}/\d{2}/\d{4}", re.MULTILINE)
_DATE = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")
_ANY_QUOTE = re.compile(r"(?=[\"“]([^\"“”«»]{12,400})[\"”»])")
_OPEN_TITLE = re.compile(r"REUNIÃO ABERTA[^\n]*?: \"([^\"\n]+)\"")
_NOT_NAMES = {"Ninguém", "Alguém", "Ele", "Ela", "Eles", "Elas", "Você", "Isso", "Isto", "Quem", "Nenhum",
              "Nenhuma", "Todos", "Todas", "Cada", "Também", "Ainda", "Já", "Não", "Como", "Quando", "Mas", "E",
              "O", "A", "Os", "As", "Um", "Uma", "Que", "Se", "Participante", "Transcrição", "Reunião"}

FALLBACK = (
    "Não existem elementos suficientes na reunião para responder com fidelidade a essa pergunta. "
    "Recomendo consultar a transcrição ou reformular a pergunta."
)


def is_portuguese(text: str) -> bool:
    words = re.findall(r"[a-zà-ÿ]+", text.lower())
    return sum(w in _PT for w in words) >= sum(w in _EN for w in words)


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


_NOT_MENTIONED = re.compile(r"^\W*isso não foi mencionado[^.\n]*[.\n]", re.IGNORECASE)


def contradicts_itself(answer: str) -> bool:
    """§3.5/§16: abre dizendo que o assunto não foi mencionado e depois responde sobre ele."""
    m = _NOT_MENTIONED.match(answer)
    return bool(m) and len(answer[m.end():].strip()) > 40


def check_answer(answer: str, context: str, question: str = "") -> list[str]:
    violations = []
    if not answer.strip():
        return ["resposta vazia"]
    if contradicts_itself(answer):
        violations.append("diz que o assunto não foi mencionado e em seguida responde sobre ele")
    if is_portuguese(question or "a reunião") and not is_portuguese(answer):
        violations.append("a resposta não está em português do Brasil")

    ctx = _normalize(context)
    for quote in _QUOTE.findall(answer):
        if len(quote.split()) >= _MIN_QUOTE_WORDS and _normalize(quote) not in ctx:
            violations.append(f"citação entre aspas que não está na transcrição: \"{quote[:80]}\"")

    # Linha citada com horário e autor: os dois precisam bater com a transcrição.
    for ts, speaker, text in _LINE.findall(answer):
        words = _normalize(text).split()[:_LINE_WORDS]
        if len(words) >= 3 and _normalize(f"{ts} {speaker}") + " " + " ".join(words) not in ctx:
            violations.append(f"trecho [{ts}] {speaker.strip()} não confere com a transcrição (horário, autor ou texto)")

    violations += _check_sources(answer, context, ctx)
    for date in dict.fromkeys(_DATE.findall(answer)):  # §20: data que não está no contexto é inventada
        if date not in context:
            violations.append(f"cita a data {date}, que não está no contexto")

    ctx_low = context.lower()
    for m in _ATTRIBUTION.finditer(answer):
        name = m.group(1) or m.group(2)
        if name not in _NOT_NAMES and name.lower() not in ctx_low:
            violations.append(f"atribui fala a \"{name}\", que não aparece na reunião")
    return list(dict.fromkeys(violations))


def _check_sources(answer: str, context: str, ctx: str) -> list[str]:
    """§20: a origem citada precisa ser a do contexto. Pega o modelo trocando a reunião de uma fala
    (eval de 2026-11-21: fala de "Acompanhamento", 10/11, citada como da reunião aberta, 03/11)."""
    violations = []
    opened = _OPEN_TITLE.search(context)
    own_lines = [l for l in context.splitlines() if _LINE.match(l.strip()) and not _CROSS_HEAD.match(l)]
    for title, date, ts, speaker, text in _CROSS.findall(answer):
        head = _normalize(f"{title} {date}")
        if ts and speaker:
            words = " ".join(_normalize(text).split()[:_LINE_WORDS])
            line = f"{_normalize(ts)} {_normalize(speaker)} {words}"
            # A reunião aberta citada pelo título: a fala está no contexto como "[hh:mm] Nome:".
            own = (opened and title.strip() == opened.group(1).strip() and head in ctx
                   and any(_normalize(l).startswith(line) for l in own_lines))
            if not own and f"{head} {line}" not in ctx:
                violations.append(f"fala citada como de [{title.strip()} · {date} · {ts}] {speaker.strip()} não "
                                  "confere com o contexto (reunião, horário, autor ou texto)")
        elif head not in ctx:
            violations.append(f"cita a reunião [{title.strip()} · {date}], que não está no contexto")

    titles = {t.strip() for t in _CROSS_HEAD.findall(context)} | ({opened.group(1)} if opened else set())
    if len(titles) < 2:
        return violations
    lines = context.splitlines()
    for m in _ANY_QUOTE.finditer(answer):  # cada aspa de abertura: "Título", Fulano disse: "fala"
        quote = _normalize(m.group(1))
        if len(quote.split()) < _MIN_QUOTE_WORDS:
            continue
        origins = set()
        for line in lines:
            if quote in _normalize(line):
                head = _CROSS_HEAD.match(line)
                origins.add(head.group(1).strip() if head else (opened.group(1) if opened else ""))
        before = answer[max(0, m.start() - 300):m.start()].lower()
        named = [t for t in titles if t.lower() in before]
        if origins and named and not origins & set(named):
            violations.append(f"atribui a fala \"{m.group(1)[:60]}\" à reunião \"{named[-1]}\", mas ela é de "
                              f"\"{sorted(origins)[0]}\"")
    return violations


DECISION_STATUSES = ("aprovada", "condicionada", "proposta", "pendente", "rejeitada", "inconclusiva")
_STATUS_ALIASES = {"aprovado": "aprovada", "aprovada": "aprovada", "condicionado": "condicionada",
                   "proposto": "proposta", "rejeitado": "rejeitada", "inconclusivo": "inconclusiva",
                   "em discussão": "proposta", "em discussao": "proposta"}


def decision_status(raw: str) -> str:
    """Estado da decisão (§7). Desconhecido vira 'inconclusiva': nunca 'aprovada' por omissão."""
    key = (raw or "").strip().lower()
    key = _STATUS_ALIASES.get(key, key)
    return key if key in DECISION_STATUSES else "inconclusiva"


def responsible_or_undefined(name: str, transcript: str) -> str:
    """§7: só há responsável se o nome aparece na reunião; senão 'Não definido'."""
    name = (name or "").strip()
    if not name or name.lower() in ("não definido", "nao definido", "null", "none", "-"):
        return "Não definido"
    return name if name.lower() in transcript.lower() else "Não definido"
