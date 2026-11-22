"""Índices da memória do agente em arquivo (ADR-022), em data/index, que a API e os workers
compartilham nos dois modos. Um arquivo por reunião (trechos + vetores) e um por dono (entidades).

ponytail: busca por força bruta em numpy; dá conta de milhares de reuniões por dono. Trocar por
índice vetorial (Atlas Vector Search, pgvector) se um dono passar de ~1 milhão de trechos.
"""
from __future__ import annotations

import json
import os
import re
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Optional

import numpy as np

_SAFE = re.compile(r"[^A-Za-z0-9_-]")


def _name(key: str) -> str:
    return _SAFE.sub("_", key or "_")  # id vem do banco, mas nunca vira caminho fora da pasta


class IndexStore:
    """Com camada quente (CAG, S14-3): os índices lidos ou gravados há pouco ficam na memória do
    processo, validados pela data do arquivo (outro processo que reindexar é percebido)."""

    HOT_MEETINGS = 64  # ~1,5 MB por reunião de 2 h: ~100 MB no pior caso

    def __init__(self, directory: str) -> None:
        self._dir = Path(directory)
        self._hot: OrderedDict[str, tuple[int, dict, np.ndarray]] = OrderedDict()
        self._lock = threading.Lock()
        self.disk_loads = 0  # ponytail: contador do processo, só para dizer o caminho nas métricas

    def load_chunks(self, meeting_id: str) -> Optional[tuple[dict, np.ndarray]]:
        path = self._dir / f"{_name(meeting_id)}.npz"
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            return None
        with self._lock:
            hot = self._hot.get(meeting_id)
            if hot and hot[0] == mtime:
                self._hot.move_to_end(meeting_id)
                return hot[1], hot[2]
        try:
            with np.load(path, allow_pickle=False) as data:
                meta, vectors = json.loads(str(data["meta"])), data["vectors"]
        except (OSError, ValueError, KeyError):
            return None  # arquivo corrompido: o chamador reindexa
        self.disk_loads += 1
        self._warm(meeting_id, mtime, meta, vectors)
        return meta, vectors

    def _warm(self, meeting_id: str, mtime: int, meta: dict, vectors: np.ndarray) -> None:
        with self._lock:
            self._hot[meeting_id] = (mtime, meta, vectors)
            self._hot.move_to_end(meeting_id)
            while len(self._hot) > self.HOT_MEETINGS:
                self._hot.popitem(last=False)

    def save_chunks(self, meeting_id: str, meta: dict, vectors: np.ndarray) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{_name(meeting_id)}.npz"
        tmp = path.with_suffix(".tmp.npz")
        vectors = vectors.astype(np.float32)
        np.savez(tmp, meta=np.array(json.dumps(meta, ensure_ascii=False)), vectors=vectors)
        os.replace(tmp, path)
        self._warm(meeting_id, path.stat().st_mtime_ns, meta, vectors)  # escrita junto com o disco

    def delete_chunks(self, meeting_id: str) -> None:
        with self._lock:
            self._hot.pop(meeting_id, None)
        (self._dir / f"{_name(meeting_id)}.npz").unlink(missing_ok=True)

    def load_entities(self, owner_id: str) -> dict:
        path = self._dir / f"entities-{_name(owner_id)}.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"entities": [], "mentions": []}

    def save_entities(self, owner_id: str, data: dict) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"entities-{_name(owner_id)}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
