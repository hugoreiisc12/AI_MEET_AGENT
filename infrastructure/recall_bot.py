"""Bot que entra no google Meet como participante e grava o audio.
Usando API do Recall.ai - compativel com Meet, Zoom e Teams

Docs: https://docs.recall.ai"""

import time
import requests
from dataclasses import dataclass 
from typing import Optional 

@dataclass
class BotSession:
    bot_id: str
    meeting_url : str = "joining"
    status: str = ""
    transcript: str = ""

class RecallBotRecoder:
    """ Envia um bot á reunião, aguardar terminar e retorna transcrição ou audio."""

    BASE_URL = "https://us-west-2.recall.ai/api/v1"
    
    def __init__(self, api_key: str, bot_name: str = "Meet Agent") -> None: 
        self.api_key = api_key
        self.bot_name = bot_name 
        self.headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json", 
        }

    def join_meeting(self, meeting_url: str) -> BotSession:
        """ Envia o botpara reunião.
         Retorna imediatamente - o bot entra de forma assíncrona.
         """
        
        response = requests.post(
            f"{self.BASE_URL}/bots/join_meeting/",
            headers=self.headers,
            json={
                "meeting_url": meeting_url,
                "bot-name": self.bot_name,
                "recording": "audio_only",
                "transcription_options": {
                   "provider": "meeting_captions",
                },
                "automatic_leave": {
                    "everyone_left_timeout": 5, 
                },

            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        return BotSession(
            bot_id=data["id"],
            meeting_url=meeting_url,
            status="joining",
        )
    
    def get_status(self, bot_id: str) -> str:
        """ Retorna status atual do bot. joining, in_call, done, error. """
        response = requests.get(
            f"{self.BASE_URL}/bots/{bot_id}/",
            headers=self.headers,
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("status_changes",  [{}])[-1].get("code", "unknown")
    def wait_until_done(self, bot_id: str, poll_interval: int = 10 , timeout: int = 7200) -> str:
        """Aguarda o bot terminar a reunião (polling).
        Retorna a transcrição final: 'done' ou 'error'. 
        """
        elapsed = 0 
        while elapsed < timeout:
            status = self.get_status(bot_id)
            if status in ("done", "call_ended", "recording_done"):
                return "done"
            if status in ("error", "fatal"):
                return "error"
            time.sleep(poll_interval)
            elapsed += poll_interval 
        return "timeout"
    
    def get_transcript(self, bot_id: str) -> Optional[str]:
        """Retorna a transcrição completa da reunião.
        Formato: 'Speaker: texto\\nSpeaker: texto...
        """

        response = requests.get(
            f"{self.BASE_URL}/bot/{bot_id}/transcript",
            headers=self.headers,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()


    def get_audio_url(self, bot_id: str) -> Optional[str]:
        """Retorna URL do arquivo de áudio gravado (válida por 24h)."""
        response = requests.get(
            f"{self.BASE_URL}/bot/{bot_id}",
            headers=self.headers,
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("media_shortcuts", {}).get("audio_mixed", {}).get("url")

    def remove_bot(self, bot_id: str) -> None:
        """Remove o bot da reunião manualmente (caso precise expulsar)."""
        requests.delete(
            f"{self.BASE_URL}/bot/{bot_id}",
            headers=self.headers,
            timeout=10,
        )