import logging
from datetime import datetime
from typing import Optional

from domain.entities.meeting import Meeting, Summary, Task, Decision
from domain.entities.speech_block import SpeechBlock
from repositories.meeting_repository import IMeetingRepository
from infrastructure.mongo_documents import (
    MeetingDocument,
    SummaryDocument,
    TaskDocument,
    DecisionDocument,
    SpeechBlockDocument,
)
from infrastructure.mongo_setup import _get_loop

logger = logging.getLogger(__name__)


class MongoMeetingRepository(IMeetingRepository):
    def _sync(self, coro):
        return _get_loop().run_until_complete(coro)

    # ── IMeetingRepository ──────────────────────────────────────────────

    def save(self, meeting: Meeting) -> None:
        self._sync(self._save(meeting))

    def find_by_id(self, meeting_id: str) -> Optional[Meeting]:
        return self._sync(self._find_by_id(meeting_id))

    def list_all(self) -> list[Meeting]:
        return self._sync(self._list_all())

    def delete(self, meeting_id: str) -> None:
        self._sync(self._delete(meeting_id))

    # ── Async internals ─────────────────────────────────────────────────

    async def _save(self, meeting: Meeting) -> None:
        doc = await MeetingDocument.find_one({"_id": meeting.id})
        if doc:
            doc.title = meeting.title
            doc.started_at = meeting.started_at
            doc.audio_path = meeting.audio_path
            doc.transcript_text = meeting.transcript_text
            doc.transcript_formatted = meeting.transcript_formatted
            doc.participants = meeting.participants
            doc.participant_info = meeting.participant_info
            doc.duration_minutes = meeting.duration_minutes
            doc.summary = self._summary_to_doc(meeting.summary) if meeting.summary else None
            doc.speech_blocks = self._blocks_to_docs(meeting.speech_blocks)
            doc.speaker_observations = meeting.speaker_observations
            doc.updated_at = datetime.now()
            doc.status = "done" if meeting.is_summarized else "transcribing" if meeting.is_transcribed else "pending"
            await doc.save()
        else:
            doc = MeetingDocument(
                id=meeting.id,
                title=meeting.title,
                started_at=meeting.started_at,
                audio_path=meeting.audio_path,
                transcript_text=meeting.transcript_text,
                transcript_formatted=meeting.transcript_formatted,
                participants=meeting.participants,
                participant_info=meeting.participant_info,
                duration_minutes=meeting.duration_minutes,
                summary=self._summary_to_doc(meeting.summary) if meeting.summary else None,
                speech_blocks=self._blocks_to_docs(meeting.speech_blocks),
                speaker_observations=meeting.speaker_observations,
                status="done" if meeting.is_summarized else "transcribing" if meeting.is_transcribed else "pending",
            )
            await doc.insert()

    async def _find_by_id(self, meeting_id: str) -> Optional[Meeting]:
        doc = await MeetingDocument.find_one({"_id": meeting_id})
        if doc is None:
            return None
        return self._doc_to_meeting(doc)

    async def _list_all(self) -> list[Meeting]:
        docs = await MeetingDocument.find_all().sort(-MeetingDocument.started_at).to_list()
        return [self._doc_to_meeting(d) for d in docs]

    async def _delete(self, meeting_id: str) -> None:
        doc = await MeetingDocument.find_one({"_id": meeting_id})
        if doc:
            await doc.delete()

    # ── Status helpers ──────────────────────────────────────────────────

    async def update_status(self, meeting_id: str, status: str) -> None:
        doc = await MeetingDocument.find_one({"_id": meeting_id})
        if doc:
            doc.status = status
            doc.updated_at = datetime.now()
            await doc.save()

    async def get_status(self, meeting_id: str) -> Optional[str]:
        doc = await MeetingDocument.find_one({"_id": meeting_id})
        if doc:
            return doc.status
        return None

    # ── Conversion helpers ──────────────────────────────────────────────

    def _summary_to_doc(self, summary: Summary) -> SummaryDocument:
        return SummaryDocument(
            overview=summary.overview,
            topics=summary.topics,
            tasks=[TaskDocument(
                description=t.description,
                responsible=t.responsible,
                deadline=t.deadline,
                done=t.done,
            ) for t in summary.tasks],
            decisions=[DecisionDocument(
                description=d.description,
                context=d.context,
            ) for d in summary.decisions],
            created_at=summary.created_at,
        )

    def _doc_to_meeting(self, doc: MeetingDocument) -> Meeting:
        summary = None
        if doc.summary:
            s = doc.summary
            summary = Summary(
                overview=s.overview,
                topics=s.topics or [],
                created_at=s.created_at or datetime.now(),
                tasks=[Task(
                    description=t.description,
                    responsible=t.responsible,
                    deadline=t.deadline,
                    done=t.done,
                ) for t in (s.tasks or [])],
                decisions=[Decision(
                    description=d.description,
                    context=d.context,
                ) for d in (s.decisions or [])],
            )
        return Meeting(
            id=doc.id,
            title=doc.title,
            started_at=doc.started_at,
            audio_path=doc.audio_path,
            transcript_text=doc.transcript_text or "",
            transcript_formatted=doc.transcript_formatted or "",
            participants=doc.participants or [],
            participant_info=doc.participant_info or {},
            duration_minutes=doc.duration_minutes or 0.0,
            summary=summary,
            speech_blocks=[
                SpeechBlock(b.user_id, b.text, b.start, b.end, b.sentiment, b.energy)
                for b in (doc.speech_blocks or [])
            ],
            speaker_observations=doc.speaker_observations or [],
        )

    def _blocks_to_docs(self, blocks: list[SpeechBlock]) -> list[SpeechBlockDocument]:
        return [
            SpeechBlockDocument(
                user_id=b.user_id,
                text=b.text,
                start=b.start,
                end=b.end,
                sentiment=b.sentiment,
                energy=b.energy,
            )
            for b in blocks
        ]
