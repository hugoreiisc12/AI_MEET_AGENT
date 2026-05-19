from pathlib import Path

path = Path("presentation/container.py")
content = path.read_text()

# =========================
# Imports
# =========================

if "AnalyzeSentimentUC" not in content:

    content = content.replace(
        "from use_cases.transcribe_meeting import TranscribeMeetingUC",
        (
            "from use_cases.transcribe_meeting import TranscribeMeetingUC\n"
            "from use_cases.analyze_sentiment import AnalyzeSentimentUC\n"
            "from use_cases.fetch_meeting_context import FetchMeetingContextUC"
        )
    )

# =========================
# Instancias
# =========================

if "analyze_sentiment =" not in content:

    content = content.replace(
        "self.repository = self._repository",
        (
            "self.repository = self._repository\n\n"
            "        # Use cases Fase 6\n"
            "        from infrastructure.llm.sentiment_analyzer import SentimentAnalyzer\n"
            "        self._sentiment_analyzer = SentimentAnalyzer(llm_client=self._llm._llm)\n"
            "        self.analyze_sentiment = AnalyzeSentimentUC(analyzer=self._sentiment_analyzer)\n\n"
            "        if settings.enable_calendar:\n"
            "            from infrastructure.calendar.google_calendar_service import GoogleCalendarService\n"
            "            self._calendar = GoogleCalendarService(\n"
            "                credentials_path=settings.google_credentials_path,\n"
            "                token_path=settings.google_token_path,\n"
            "            )\n"
            "            self.fetch_meeting_context = FetchMeetingContextUC(self._calendar)\n"
            "        else:\n"
            "            self.fetch_meeting_context = None"
        )
    )

path.write_text(content)

print("container.py atualizado")
