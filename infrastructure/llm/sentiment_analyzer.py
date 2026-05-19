""" infraestrutura/llm/sentiment_analyze.py 

  Analise sentimento o engajamento por speaker na transcrição.
  Usa LLM para identificar tom, energia e participação de cada speaker.

Não modifica nenhuma entity existente — retorna SentimentResult separado 
"""
from __future__ import annotations

import json
from llm.langchain_llm_service import LLMServiceError
from entities.sentiment_result import SentimentResult, SpeakerSentiment
from typing import Optional

from interface.llm_services import LLMServiceError


# Classe SpeakerSentiment removida daqui — use a do entities.sentiment_result ao invés


SENTIMENT_PROMPT = """Você é um especialista em análise de comunicação e dinâmica de equipes.
Analise a transcrição abaixo e retorne um JSON com a seguinte estrutura exata:

{
  "overall_tone": "positivo|neutro|negativo|misto",
  "energy_level": "alto|médio|baixo",
  "meeting_mood": "frase curta descrevendo o clima geral da reunião",
  "collaboration_score": 0.0 a 1.0,
  "tension_moments": ["descrição breve de momento de tensão se houver"],
  "positive_moments": ["descrição breve de momento positivo se houver"],
  "speakers": [
    {
      "speaker": "SPEAKER_00",
      "overall_tone": "positivo|neutro|negativo|misto",
      "energy_level": "alto|médio|baixo",
      "engagement_score": 0.0 a 1.0,
      "talk_time_ratio": 0.0 a 1.0,
      "key_emotions": ["emoção 1", "emoção 2"],
      "highlights": ["trecho representativo curto"]
    }
  ]
}

Regras:
- Responda APENAS com JSON válido, sem texto antes ou depois
- Baseie-se apenas no que está na transcrição — não especule
- talk_time_ratio deve somar aproximadamente 1.0 entre todos os speakers
- collaboration_score alto = discussão construtiva, respeito mútuo, ideias complementares
- Escreva em português do Brasil
"""


class SentimentAnalyzer:
    """
    Analisa sentimento e engajamento de uma transcrição.
    Classe pura — recebe o cliente LLM via injeção.
    """

    def __init__(self, llm_client) -> None:
        self._client = llm_client

    def analyze(self, transcript: str) -> SentimentResult:
        """
        Analisa o sentimento e engajamento da transcrição.

        Args:
            transcript: Texto formatado da reunião (com speakers)

        Returns:
            SentimentResult com análise completa
        """
        try:
            from langchain_core.messages import SystemMessage, HumanMessage

            messages = [
                SystemMessage(content=SENTIMENT_PROMPT),
                HumanMessage(content=f"TRANSCRIÇÃO:\n\n{transcript}"),
            ]
            response = self._client.invoke(messages)
            return self._parse(response.content)

        except Exception as e:
            raise LLMServiceError(f"Análise de sentimento falhou: {str(e)}") from e

    def _parse(self, raw: str) -> SentimentResult:
        """Converte JSON do LLM em SentimentResult."""
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        cleaned = cleaned.strip()

        try:
            data = json.loads(cleaned)

            speakers = [
                SpeakerSentiment(
                    speaker=s.get("speaker", ""),
                    overall_tone=s.get("overall_tone", "neutro"),
                    energy_level=s.get("energy_level", "médio"),
                    engagement_score=float(s.get("engagement_score", 0.5)),
                    talk_time_ratio=float(s.get("talk_time_ratio", 0.0)),
                    key_emotions=s.get("key_emotions", []),
                    highlights=s.get("highlights", []),
                )
                for s in data.get("speakers", [])
            ]

            return SentimentResult(
                overall_tone=data.get("overall_tone", "neutro"),
                energy_level=data.get("energy_level", "médio"),
                meeting_mood=data.get("meeting_mood", ""),
                collaboration_score=float(data.get("collaboration_score", 0.5)),
                tension_moments=data.get("tension_moments", []),
                positive_moments=data.get("positive_moments", []),
                speakers=speakers,
            )

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            raise LLMServiceError(
                f"Sentimento: JSON inválido — {str(e)}\nResposta: {raw[:200]}"
            ) from e


