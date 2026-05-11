# Repositório de reuniões usando arquivos de JSON para persistência simples 
# e sem dependências externas, ideal para prototipagem
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from entities.metting import Meeting, Summary, Task, Decision  # CORRIGIDO: domain.entities → entities
from config.settings import get_settings


# Defindo classe de repositório que persiste reuniões como arquivos JSON individuais em disco
# (Removida herança de IMeetingRepository para evitar import circular e facilitar testes)
class JsonMeetingRepository:  # CORRIGIDO: Removida herança de IMeetingRepository (não definido)
    """
    Persiste reuniões como arquivos JSON individuais em disco.
    Cada reunião = um arquivo {meeting_id}.json na pasta configurada.

    Simples, sem dependência de banco de dados.
    Fácil de migrar para SQLite ou Postgres no futuro implementando IMeetingRepository.
    """

# Construtor que recebe o caminho de armazenamento opcionalmente, criando a pasta se não existir, 
# e garatindo que o repositório esteja pronto para uso.
    def __init__(self, storage_path: str | None = None) -> None:
        path = storage_path or get_settings().storage_path
        self._base_path = Path(path)
        self._base_path.mkdir(parents=True, exist_ok=True)

# IMeetingRepository
# Implementando metodo de contrato para persintência de reuniões, incluindo salvar, buscar por ID, Listar todas e deletar reuniões por ID, utilizando arquivos JSON para armazenamento e leitura 
    def save(self, meeting: Meeting) -> None:
        file_path = self._path_for(meeting.id)
        data = self._serialize(meeting)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

# Implementando metodo de contrato para buscar reunião por ID, que lê arquivo JSON correspondente, disserializa e retorna a reunião
    def find_by_id(self, meeting_id: str) -> Optional[Meeting]:
        file_path = self._path_for(meeting_id)
        if not file_path.exists():
            return None
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return self._deserialize(data)

# Implementando metodo de contrato para listar todas as reuniões salvas, que  lê todos os arquivos JSON na pasta 
    def list_all(self) -> list[Meeting]:
        meetings = []
        for file in sorted(self._base_path.glob("*.json"), reverse=True):
            with open(file, "r", encoding="utf-8") as f:
                data = json.load(f)
            meetings.append(self._deserialize(data))
        return meetings
# Implementando metodo de contrato para deletar reunião por ID, que remove o arquivo JSON correspondente do armazenamento persistente 
    def delete(self, meeting_id: str) -> None:
        file_path = self._path_for(meeting_id)
        if file_path.exists():
            os.remove(file_path)

# Serialização / Deserialização privadas
# Metodos auxiliares para conversar entre a entity Meeting do dominio e o formato JSON utilizando a persistencia em arquivos 
    def _path_for(self, meeting_id: str) -> Path:
        return self._base_path / f"{meeting_id}.json"

# Metodo de serialização que converte a entity Meeting em um dicionário pronto para ser salvo como JSON 
    def _serialize(self, meeting: Meeting) -> dict:
        data: dict = {
            "id": meeting.id,
            "title": meeting.title,
            "started_at": meeting.started_at.isoformat(),
            "audio_path": meeting.audio_path,
            "transcript_text": meeting.transcript_text,
            "transcript_formatted": meeting.transcript_formatted,
            "participants": meeting.participants,
            "duration_minutes": meeting.duration_minutes,
            "summary": None,
        }
# Anexa o resumo á serialização da reunião se o resumo estiver presente, convertendo a entity Summary e suas subentidades 
        if meeting.summary:
            s = meeting.summary
            data["summary"] = {
                "overview": s.overview,
                "topics": s.topics,
                "created_at": s.created_at.isoformat(),
                "tasks": [
                    {
                        "description": t.description,
                        "responsible": t.responsible,
                        "deadline": t.deadline,
                        "done": t.done,
                    }
                    for t in s.tasks
                ],
                "decisions": [
                    {
                        "description": d.description,
                        "context": d.context,
                    }
                    for d in s.decisions
                ],
            }

        return data

# Metodo de deserialização que converte um dicionário lido do JSON em uma entity Meeting, incluindo a construção da entity Summary 
    def _deserialize(self, data: dict) -> Meeting:
        summary = None
        if data.get("summary"):
            s = data["summary"]
            summary = Summary(
                overview=s.get("overview", ""),
                topics=s.get("topics", []),
                created_at=datetime.fromisoformat(s.get("created_at", datetime.now().isoformat())),
                tasks=[
                    Task(
                        description=t["description"],
                        responsible=t.get("responsible", "Não definido"),
                        deadline=t.get("deadline", "Não definido"),
                        done=t.get("done", False),
                    )
                    for t in s.get("tasks", [])
                ],
                decisions=[
                    Decision(
                        description=d["description"],
                        context=d.get("context", ""),
                    )
                    for d in s.get("decisions", [])
                ],
            )

        return Meeting(
            id=data["id"],
            title=data["title"],
            started_at=datetime.fromisoformat(data["started_at"]),
            audio_path=data.get("audio_path"),
            transcript_text=data.get("transcript_text", ""),
            transcript_formatted=data.get("transcript_formatted", ""),
            participants=data.get("participants", []),
            duration_minutes=data.get("duration_minutes", 0.0),
            summary=summary,
        )