"""Memória longa do agente (ADR-022, Sprint 13).

- Trechos (S13-1): falas seguidas da transcrição, com horário e oradores, sobrepostas em uma fala
  para a resposta não cair na fronteira entre dois trechos. Cada trecho tem um vetor (IEmbedder).
- Busca híbrida (S13-3): ranking por palavra e ranking por vetor, somados por posição (RRF). A
  palavra acerta nomes e números; o vetor acerta paráfrases ("quanto custa" ≈ "cobra por mês").
- Entidades (S13-2): pessoas (com apelidos) e tópicos (agrupados por similaridade) ligando as
  reuniões do mesmo dono; decisões e tarefas viram menções do tópico e do responsável.

O índice é derivado da reunião: muda a transcrição (nomes trocados, reprocessamento), ele é refeito
na próxima consulta. Sempre por dono: nada daqui sai para outro usuário (S13-5).
"""
from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
import uuid
from collections import defaultdict

import numpy as np

from domain.entities.meeting import Meeting
from use_cases.llm_context import _words

logger = logging.getLogger(__name__)

CHUNK_CHARS = 600
RRF_K = 60
# Calibrado com intfloat/multilingual-e5-small (2026-11-21): o mesmo tópico em outras palavras deu
# 0,934–0,969; tópicos diferentes, até 0,922 ("migração para a nuvem" × "migração do sistema de RH").
# Outro modelo de embeddings pede nova calibração.
TOPIC_SAME = 0.93
_LINE = re.compile(r"^\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*([^:\]\n]{1,60}):")
_GENERIC_SPEAKER = re.compile(r"^(speaker|falante|participante|locutor)[\s_]*\d+$", re.IGNORECASE)


def chunk_transcript(text: str, max_chars: int = CHUNK_CHARS) -> list[dict]:
    """Falas seguidas até `max_chars`, sem cortar fala; cada trecho repete a última fala do anterior."""
    lines = [line for line in text.splitlines() if line.strip()]
    chunks: list[dict] = []
    i = 0
    while i < len(lines):
        j, size = i, 0
        while j < len(lines) and (j == i or size + len(lines[j]) <= max_chars):
            size += len(lines[j]) + 1
            j += 1
        block = lines[i:j]
        heads = [m for m in map(_LINE.match, block) if m]
        chunks.append({"start": heads[0].group(1) if heads else "",
                       "speakers": list(dict.fromkeys(m.group(2).strip() for m in heads)),
                       "text": "\n".join(block)})
        if j >= len(lines):
            break
        i = max(j - 1, i + 1)
    return chunks


class MeetingIndex:
    def __init__(self, store, embedder) -> None:
        self._store = store
        self._embedder = embedder

    def _digest(self, meeting: Meeting) -> str:
        text = meeting.transcript_formatted or meeting.transcript_text
        return hashlib.sha1(f"{self._embedder.model_name}\n{text}".encode()).hexdigest()

    def ensure(self, meeting: Meeting) -> tuple[list[dict], np.ndarray]:
        """Trechos e vetores da reunião, refeitos se a transcrição, o modelo ou o dono mudaram."""
        digest = self._digest(meeting)
        found = self._store.load_chunks(meeting.id)
        if found and found[0].get("digest") == digest and found[0].get("owner_id") == meeting.owner_id:
            return found[0]["chunks"], found[1]
        chunks = chunk_transcript(meeting.transcript_formatted or meeting.transcript_text)
        vectors = np.array(self._embedder.embed_documents([c["text"] for c in chunks]), dtype=np.float32)
        vectors = vectors.reshape(len(chunks), -1)
        self._store.save_chunks(meeting.id, {"owner_id": meeting.owner_id, "digest": digest,
                                             "model": self._embedder.model_name, "chunks": chunks}, vectors)
        return chunks, vectors

    def search(self, meeting: Meeting, question: str, max_chars: int) -> str:
        """Trechos mais ligados à pergunta, do mais ao menos relevante, até `max_chars`."""
        chunks, vectors = self.ensure(meeting)
        chosen = _pick(self._rank(chunks, vectors, question), [c["text"] for c in chunks], max_chars)
        return "\n[...]\n".join(chunks[i]["text"] for i in chosen)

    def search_many(self, meetings: list[Meeting], question: str, max_chars: int,
                    related: set[str] = frozenset()) -> str:
        """Entre reuniões (S14-1): os trechos das reuniões dadas (só as do dono: quem chama passa a
        lista do repositório filtrada por dono) com cada fala citada como [Título · data · horário].
        Sobem na ordem as reuniões ligadas por entidade (`related`) e as mais recentes."""
        pool: list[tuple[Meeting, dict]] = []
        vectors = []
        for m in meetings:
            if not m.is_transcribed:
                continue
            chunks, v = self.ensure(m)
            pool += [(m, c) for c in chunks]
            vectors.append(v)
        if not pool:
            return ""
        score = self._rank([c for _, c in pool], np.vstack(vectors), question)
        recency = {m.id: r for r, m in enumerate(sorted({m.id: m for m, _ in pool}.values(),
                                                        key=lambda m: m.started_at, reverse=True))}
        for i, (m, _) in enumerate(pool):
            score[i] = score.get(i, 0) + (1 / RRF_K if m.id in related else 0) + 0.5 / (RRF_K + recency[m.id])
        texts = [_cite(m, c["text"]) for m, c in pool]
        return "\n[...]\n".join(texts[i] for i in _pick(score, texts, max_chars))

    def _rank(self, chunks: list[dict], vectors: np.ndarray, question: str) -> dict[int, float]:
        """Posição por vetor e por palavra, somadas (RRF)."""
        if not chunks:
            return {}
        query = np.array(self._embedder.embed_query(question), dtype=np.float32)
        by_vector = np.argsort(-(vectors @ query), kind="stable")
        wanted = _words(question)
        overlap = [len(wanted & _words(c["text"])) for c in chunks]
        by_word = sorted(range(len(chunks)), key=lambda i: (-overlap[i], i))
        score: dict[int, float] = defaultdict(float)
        for rank, i in enumerate(by_vector):
            score[int(i)] += 1 / (RRF_K + rank)
        for rank, i in enumerate(by_word):
            if overlap[i]:
                score[i] += 1 / (RRF_K + rank)
        return score


def _pick(score: dict[int, float], texts: list[str], max_chars: int) -> list[int]:
    chosen, used = [], 0
    for i in sorted(score, key=lambda i: -score[i]):
        if used + len(texts[i]) > max_chars and chosen:
            continue
        chosen.append(i)
        used += len(texts[i])
    return chosen


def _cite(meeting: Meeting, text: str) -> str:
    """[00:15] Bruno: ... → [Título · 10/11/2026 · 00:15] Bruno: ... (formato do §20)."""
    head = f"{meeting.title} · {meeting.started_at:%d/%m/%Y}"
    return "\n".join(re.sub(r"^\[([^\]]+)\]", lambda m: f"[{head} · {m.group(1)}]", line) for line in text.splitlines())


def _norm(name: str) -> str:
    plain = unicodedata.normalize("NFKD", name.casefold()).encode("ascii", "ignore").decode()
    return " ".join(re.findall(r"[a-z0-9]+", plain))


class EntityLinker:
    """Pessoas e tópicos do dono, ligados entre reuniões (S13-2)."""

    def __init__(self, store, embedder) -> None:
        self._store = store
        self._embedder = embedder

    def link(self, meeting: Meeting) -> dict:
        data = self._store.load_entities(meeting.owner_id)
        entities = data["entities"]
        mentions = [m for m in data["mentions"] if m["meeting_id"] != meeting.id]  # refazer não duplica

        def mention(entity: dict, kind: str, text: str, **extra) -> None:
            mentions.append({"entity": entity["id"], "meeting_id": meeting.id, "kind": kind, "text": text, **extra})

        summary = meeting.summary
        for name in meeting.participants:
            if (person := self._person(entities, name)) is not None:
                mention(person, "participante", name)
        topics: list[tuple[dict, np.ndarray]] = []
        if summary and summary.topics:
            for text, vector in zip(summary.topics, self._embedder.embed_documents(summary.topics)):
                topics.append((self._topic(entities, text, np.array(vector, dtype=np.float32)), np.array(vector)))
                mention(topics[-1][0], "tópico", text)
        items = [("decisão", d.description, {"status": d.status}, None) for d in (summary.decisions if summary else [])]
        items += [("tarefa", t.description, {"done": t.done}, t.responsible) for t in (summary.tasks if summary else [])]
        items += [("questão em aberto", q, {}, None) for q in (summary.open_questions if summary else [])]
        items += [("impacto", f"{t['topic']} → {t['decision']}", {"effect": t.get("effect", "")}, None)
                  for t in (summary.topic_decisions if summary else [])]
        vectors = self._embedder.embed_documents([text for _, text, _, _ in items]) if items and topics else []
        for n, (kind, text, extra, responsible) in enumerate(items):
            if topics:  # decisão e tarefa ficam no tópico desta reunião mais parecido com elas
                best = max(topics, key=lambda t: float(t[1] @ np.array(vectors[n])))
                mention(best[0], kind, text, **extra)
            if responsible and (person := self._person(entities, responsible)) is not None:
                mention(person, kind, text, **extra)
        data = {"entities": entities, "mentions": mentions}
        self._store.save_entities(meeting.owner_id, data)
        return data

    def related_meetings(self, meeting: Meeting, question: str) -> set[str]:
        """Reuniões do dono ligadas à aberta ou à pergunta: mesma pessoa ou tópico citado na pergunta
        (pelo nome ou apelido) ou mesmo tópico da reunião aberta."""
        data = self._store.load_entities(meeting.owner_id)
        asked = f" {_norm(question)} "
        wanted = {e["id"] for e in data["entities"] if any(f" {a} " in asked for a in e["aliases"])}
        wanted |= {m["entity"] for m in data["mentions"] if m["meeting_id"] == meeting.id and m["kind"] == "tópico"}
        return {m["meeting_id"] for m in data["mentions"] if m["entity"] in wanted} - {meeting.id}

    @staticmethod
    def _person(entities: list[dict], name: str) -> dict | None:
        """Mesmo nome normalizado = mesma pessoa. Primeiro nome sozinho ("Ana") liga a "Ana Souza" se
        só houver uma Ana; duas pessoas com nome completo diferente nunca se juntam."""
        key = _norm(name)
        if not key or key in ("nao definido", "voce", "you") or _GENERIC_SPEAKER.match(key):
            return None
        people = [e for e in entities if e["kind"] == "pessoa"]
        for e in people:
            if key in e["aliases"]:
                return e
        first, single = key.split()[0], len(key.split()) == 1
        same_first = [e for e in people if any(a.split()[0] == first for a in e["aliases"])]
        if len(same_first) == 1 and (single or all(len(a.split()) == 1 for a in same_first[0]["aliases"])):
            same_first[0]["aliases"].append(key)
            if not single:
                same_first[0]["name"] = name.strip()  # o nome completo é o mais útil para mostrar
            return same_first[0]
        entity = {"id": uuid.uuid4().hex[:12], "kind": "pessoa", "name": name.strip(), "aliases": [key]}
        entities.append(entity)
        return entity

    @staticmethod
    def _topic(entities: list[dict], text: str, vector: np.ndarray) -> dict:
        best, best_score = None, TOPIC_SAME
        for e in entities:
            if e["kind"] == "tópico":
                score = float(np.array(e["vector"], dtype=np.float32) @ vector)
                if score >= best_score:
                    best, best_score = e, score
        if best is not None:
            if _norm(text) not in best["aliases"]:
                best["aliases"].append(_norm(text))
            return best
        entity = {"id": uuid.uuid4().hex[:12], "kind": "tópico", "name": text.strip(), "aliases": [_norm(text)],
                  "vector": [round(float(x), 5) for x in vector]}
        entities.append(entity)
        return entity


class MemoryIndexer:
    """O que o pipeline e o chat usam. Falha aqui nunca derruba resumo nem chat: o agente
    continua com a busca por palavra (llm_context.select_relevant)."""

    def __init__(self, store, embedder) -> None:
        self.store = store
        self.chunks = MeetingIndex(store, embedder)
        self.entities = EntityLinker(store, embedder)

    def index(self, meeting: Meeting) -> None:
        try:
            if meeting.is_transcribed:
                self.chunks.ensure(meeting)
            if meeting.summary:
                self.entities.link(meeting)
        except Exception:
            logger.exception("[%s] não foi possível indexar a reunião para a memória", meeting.id)

    def forget(self, meeting: Meeting) -> None:
        """Reunião apagada: some do índice e das menções."""
        self.store.delete_chunks(meeting.id)
        data = self.store.load_entities(meeting.owner_id)
        data["mentions"] = [m for m in data["mentions"] if m["meeting_id"] != meeting.id]
        used = {m["entity"] for m in data["mentions"]}
        data["entities"] = [e for e in data["entities"] if e["id"] in used]
        self.store.save_entities(meeting.owner_id, data)
