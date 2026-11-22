"""Usuários, sessões e códigos de recuperação (ADR-011): MongoDB no colaborativo, JSON no solo.

Coleções:
  users            {_id, name, email (único), password_hash, created_at, role,
                    failed_logins, locked_until}
  sessions         {_id: sha256(token), user_id, created_at, expires_at, user_agent, ip}
  password_resets  {_id: user_id, code_hash, expires_at, attempts}
Os índices TTL em `expires_at` apagam sessões e códigos vencidos sozinhos.
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

from domain.entities.user import User

_USER_FIELDS = ("name", "email", "password_hash", "created_at", "role", "failed_logins", "locked_until")


def _to_user(doc: Optional[dict]) -> Optional[User]:
    if not doc:
        return None
    return User(id=doc["_id"], **{k: doc[k] for k in _USER_FIELDS if k in doc})


class MongoAuthStore:
    def __init__(self, mongo_uri: str, db_name: str) -> None:
        db = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)[db_name]
        self._users, self._sessions, self._resets = db["users"], db["sessions"], db["password_resets"]
        self._indexed = False

    def _ensure_indexes(self) -> None:
        # Na primeira escrita, e não no construtor: a aplicação sobe mesmo com o banco fora.
        if not self._indexed:
            self._users.create_index("email", unique=True)
            self._sessions.create_index("expires_at", expireAfterSeconds=0)
            self._sessions.create_index("user_id")
            self._resets.create_index("expires_at", expireAfterSeconds=0)
            self._indexed = True

    # ── Usuários ──────────────────────────────────────────────────────

    def add_user(self, user: User) -> bool:
        """False se o e-mail já existe."""
        self._ensure_indexes()
        try:
            self._users.insert_one({"_id": user.id, **{k: getattr(user, k) for k in _USER_FIELDS}})
            return True
        except DuplicateKeyError:
            return False

    def user_by_email(self, email: str) -> Optional[User]:
        return _to_user(self._users.find_one({"email": email}))

    def user_by_id(self, user_id: str) -> Optional[User]:
        return _to_user(self._users.find_one({"_id": user_id}))

    def list_users(self) -> list[User]:
        return [_to_user(d) for d in self._users.find()]

    def count_users(self) -> int:
        return self._users.count_documents({})

    def count_active_sessions(self) -> int:
        from use_cases.auth import utcnow
        return self._sessions.count_documents({"expires_at": {"$gt": utcnow()}})

    def update_user(self, user_id: str, fields: dict) -> None:
        self._users.update_one({"_id": user_id}, {"$set": fields})

    # ── Sessões ───────────────────────────────────────────────────────

    def add_session(self, session: dict) -> None:
        self._ensure_indexes()
        self._sessions.insert_one(session)

    def session(self, sid: str) -> Optional[dict]:
        return self._sessions.find_one({"_id": sid})

    def sessions_of(self, user_id: str) -> list[dict]:
        return list(self._sessions.find({"user_id": user_id}))

    def delete_session(self, sid: str) -> None:
        self._sessions.delete_one({"_id": sid})

    def delete_sessions(self, user_id: Optional[str] = None, keep: Optional[str] = None,
                        expired_before: Optional[datetime] = None) -> int:
        query: dict = {}
        if user_id is not None:
            query["user_id"] = user_id
        if keep:
            query["_id"] = {"$ne": keep}
        if expired_before is not None:
            query["expires_at"] = {"$lt": expired_before}
        return self._sessions.delete_many(query).deleted_count

    # ── Recuperação de senha ──────────────────────────────────────────

    def put_reset(self, reset: dict) -> None:
        self._ensure_indexes()
        self._resets.replace_one({"_id": reset["_id"]}, reset, upsert=True)

    def get_reset(self, user_id: str) -> Optional[dict]:
        return self._resets.find_one({"_id": user_id})

    def update_reset(self, user_id: str, fields: dict) -> None:
        self._resets.update_one({"_id": user_id}, {"$set": fields})

    def delete_reset(self, user_id: str) -> None:
        self._resets.delete_one({"_id": user_id})


def _json_default(value):
    if isinstance(value, datetime):
        return {"__dt__": value.isoformat()}
    raise TypeError(f"Não serializável: {type(value)}")


def _json_hook(obj: dict):
    return datetime.fromisoformat(obj["__dt__"]) if set(obj) == {"__dt__"} else obj


class JsonAuthStore:
    """Mesmo contrato do MongoAuthStore, num arquivo JSON: login no modo solo (sem MongoDB).
    Sessões e códigos vencidos não somem sozinhos como no TTL do Mongo; o AuthService já
    ignora os vencidos, e a limpeza fica com purge_sessions / expired_before.
    ponytail: arquivo inteiro relido e regravado a cada operação, com trava de processo;
    serve para um computador e poucas contas. Para muitas contas ou vários processos, usar o Mongo."""

    def __init__(self, path: str) -> None:
        import threading
        self._path = Path(path)
        self._lock = threading.RLock()

    def _load(self) -> dict:
        if not self._path.exists():
            return {"users": {}, "sessions": {}, "resets": {}}
        with open(self._path, encoding="utf-8") as f:
            return json.load(f, object_hook=_json_hook)

    def _save(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, default=_json_default, ensure_ascii=False, indent=2)
        os.replace(tmp, self._path)

    # ── Usuários ──────────────────────────────────────────────────────

    def add_user(self, user: User) -> bool:
        with self._lock:
            data = self._load()
            if any(u["email"] == user.email for u in data["users"].values()):
                return False
            data["users"][user.id] = {"_id": user.id, **{k: getattr(user, k) for k in _USER_FIELDS}}
            self._save(data)
            return True

    def user_by_email(self, email: str) -> Optional[User]:
        with self._lock:
            return _to_user(next((u for u in self._load()["users"].values() if u["email"] == email), None))

    def user_by_id(self, user_id: str) -> Optional[User]:
        with self._lock:
            return _to_user(self._load()["users"].get(user_id))

    def list_users(self) -> list[User]:
        with self._lock:
            return [_to_user(u) for u in self._load()["users"].values()]

    def count_users(self) -> int:
        with self._lock:
            return len(self._load()["users"])

    def count_active_sessions(self) -> int:
        from use_cases.auth import utcnow
        now = utcnow()
        with self._lock:
            return sum(1 for s in self._load()["sessions"].values() if s["expires_at"] > now)

    def update_user(self, user_id: str, fields: dict) -> None:
        with self._lock:
            data = self._load()
            if user_id in data["users"]:
                data["users"][user_id].update(fields)
                self._save(data)

    # ── Sessões ───────────────────────────────────────────────────────

    def add_session(self, session: dict) -> None:
        with self._lock:
            data = self._load()
            data["sessions"][session["_id"]] = session
            self._save(data)

    def session(self, sid: str) -> Optional[dict]:
        with self._lock:
            return self._load()["sessions"].get(sid)

    def sessions_of(self, user_id: str) -> list[dict]:
        with self._lock:
            return [s for s in self._load()["sessions"].values() if s["user_id"] == user_id]

    def delete_session(self, sid: str) -> None:
        with self._lock:
            data = self._load()
            if data["sessions"].pop(sid, None) is not None:
                self._save(data)

    def delete_sessions(self, user_id: Optional[str] = None, keep: Optional[str] = None,
                        expired_before: Optional[datetime] = None) -> int:
        with self._lock:
            data = self._load()
            doomed = [sid for sid, s in data["sessions"].items()
                      if (user_id is None or s["user_id"] == user_id) and sid != keep
                      and (expired_before is None or s["expires_at"] < expired_before)]
            for sid in doomed:
                del data["sessions"][sid]
            if doomed:
                self._save(data)
            return len(doomed)

    # ── Recuperação de senha ──────────────────────────────────────────

    def put_reset(self, reset: dict) -> None:
        with self._lock:
            data = self._load()
            data["resets"][reset["_id"]] = dict(reset)
            self._save(data)

    def get_reset(self, user_id: str) -> Optional[dict]:
        with self._lock:
            return self._load()["resets"].get(user_id)

    def update_reset(self, user_id: str, fields: dict) -> None:
        with self._lock:
            data = self._load()
            if user_id in data["resets"]:
                data["resets"][user_id].update(fields)
                self._save(data)

    def delete_reset(self, user_id: str) -> None:
        with self._lock:
            data = self._load()
            if data["resets"].pop(user_id, None) is not None:
                self._save(data)
