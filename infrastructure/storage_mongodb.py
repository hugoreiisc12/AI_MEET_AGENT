import asyncio
from datetime import datetime
from typing import Optional

from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from domain.entities.meeting import Meeting, Summary, Task, Decision
from infrastructure.mongodb_documents import (
    MeetingDocument,
    SummaryEmbedded,
    TaskEmbedded,
    DecisionEmbedded,
)
from repositories.meeting_repository import IMeetingRepository


_loop: asyncio.AbstractEventLoop | None = None


def _get_loop() -> asyncio.AbstractEventLoop:
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
    return _loop


def _run_async(coro):
    return _get_loop().run_until_complete(coro)


def _task_to_embedded(t: Task) -> TaskEmbedded:
    return TaskEmbedded(
        description=t.description,
        responsible=t.responsible,
        deadline=t.deadline,
        done=t.done,
    )


def _decision_to_embedded(d: Decision) -> DecisionEmbedded:
    return DecisionEmbedded(description=d.description, context=d.context)


def _summary_to_embedded(s: Summary) -> SummaryEmbedded:
    return SummaryEmbedded(
        overview=s.overview,
        topics=s.topics,
        tasks=[_task_to_embedded(t) for t in s.tasks],
        decisions=[_decision_to_embedded(d) for d in s.decisions],
        created_at=s.created_at,
    )


def _embedded_to_task(e: TaskEmbedded) -> Task:
    return Task(
        description=e.description,
        responsible=e.responsible,
        deadline=e.deadline,
        done=e.done,
    )


def _embedded_to_decision(e: DecisionEmbedded) -> Decision:
    return Decision(description=e.description, context=e.context)


def _embedded_to_summary(e: SummaryEmbedded) -> Summary:
    return Summary(
        overview=e.overview,
        topics=e.topics,
        tasks=[_embedded_to_task(t) for t in e.tasks],
        decisions=[_embedded_to_decision(d) for d in e.decisions],
        created_at=e.created_at,
    )


def _doc_to_entity(doc: MeetingDocument) -> Meeting:
    summary = None
    if doc.summary:
        summary = _embedded_to_summary(doc.summary)
    return Meeting(
        id=doc.id,
        title=doc.title,
        started_at=doc.started_at,
        audio_path=doc.audio_path,
        transcript_text=doc.transcript_text,
        transcript_formatted=doc.transcript_formatted,
        transcript_raw=doc.transcript_raw if hasattr(doc, 'transcript_raw') else "",
        participants=doc.participants,
        duration_minutes=doc.duration_minutes,
        summary=summary,
    )


def _entity_to_doc(meeting: Meeting) -> MeetingDocument:
    summary = None
    if meeting.summary:
        summary = _summary_to_embedded(meeting.summary)
    return MeetingDocument(
        id=meeting.id,
        title=meeting.title,
        started_at=meeting.started_at,
        audio_path=meeting.audio_path,
        transcript_text=meeting.transcript_text,
        transcript_formatted=meeting.transcript_formatted,
        transcript_raw=meeting.transcript_raw,
        participants=meeting.participants,
        duration_minutes=meeting.duration_minutes,
        summary=summary,
    )


class MongoDBMeetingRepository(IMeetingRepository):
    def __init__(self, mongo_uri: str, db_name: str = "meetagent") -> None:
        self._uri = mongo_uri
        self._db_name = db_name
        self._initialized = False

    def _ensure_init(self):
        if not self._initialized:
            _run_async(self._init_beanie())
            self._initialized = True

    async def _ensure_init_async(self):
        if not self._initialized:
            await self._init_beanie()
            self._initialized = True

    async def _init_beanie(self):
        if MeetingDocument._document_settings is not None:
            self._initialized = True
            return
        client = AsyncIOMotorClient(self._uri)
        await init_beanie(
            database=client[self._db_name],
            document_models=[MeetingDocument],
        )

    def save(self, meeting: Meeting) -> None:
        self._ensure_init()
        _run_async(self._save(meeting))

    async def _save(self, meeting: Meeting):
        doc = _entity_to_doc(meeting)
        await doc.save()

    def find_by_id(self, meeting_id: str) -> Optional[Meeting]:
        self._ensure_init()
        return _run_async(self._find_by_id(meeting_id))

    async def _find_by_id(self, meeting_id: str) -> Optional[Meeting]:
        doc = await MeetingDocument.get(meeting_id)
        if doc is None:
            return None
        return _doc_to_entity(doc)

    def list_all(self) -> list[Meeting]:
        self._ensure_init()
        return _run_async(self._list_all())

    async def _list_all(self) -> list[Meeting]:
        docs = await MeetingDocument.find_all().sort(-MeetingDocument.started_at).to_list()
        return [_doc_to_entity(d) for d in docs]

    def delete(self, meeting_id: str) -> None:
        self._ensure_init()
        _run_async(self._delete(meeting_id))

    async def _delete(self, meeting_id: str):
        doc = await MeetingDocument.get(meeting_id)
        if doc:
            await doc.delete()
