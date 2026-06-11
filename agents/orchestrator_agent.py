"""
Orchestrator Agent — Controla todo o fluxo da pipeline.

Fluxo completo:
  1. Bot é enviado para a reunião
  2. Bot entra na reunião
  3. Bot começa a gravar (ORQUESTRADOR VALIDA)
  4. Bot fica até a reunião acabar
  5. Detecta que a reunião acabou e encerra gravação
  6. Salva arquivo .webm
  7. ETL Agent: .webm → WhisperLocal → transcrição → MongoDB
  8. Collection Agent: DB → Interface
  9. Usuário consulta reunião e abre chat

Cada etapa é um bloco validado individualmente.
Se qualquer etapa falhar, retorna erro específico.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Callable, Optional
from pathlib import Path

from domain.entities.meeting import Meeting
from repositories.meeting_repository import IMeetingRepository


class PipelineStep:
    """Representa uma etapa validada do pipeline."""

    def __init__(
        self,
        name: str,
        status: str = "pending",
        detail: str = "",
    ) -> None:
        self.name = name
        self.status = status  # pending | running | ok | fail
        self.detail = detail
        self.started_at: Optional[datetime] = None
        self.finished_at: Optional[datetime] = None

    def start(self) -> None:
        self.status = "running"
        self.started_at = datetime.now()

    def ok(self, detail: str = "") -> None:
        self.status = "ok"
        self.finished_at = datetime.now()
        self.detail = detail

    def fail(self, detail: str = "") -> None:
        self.status = "fail"
        self.finished_at = datetime.now()
        self.detail = detail


class PipelineResult:
    """Resultado completo da execução do pipeline."""

    def __init__(self) -> None:
        self.meeting_id: str = ""
        self.audio_path: str = ""
        self.success: bool = False
        self.error: str = ""
        self.steps: list[PipelineStep] = []

    @property
    def failed_step(self) -> Optional[PipelineStep]:
        for s in self.steps:
            if s.status == "fail":
                return s
        return None


class OrchestratorAgent:
    """Orquestrador que controla todo o fluxo da pipeline."""

    def __init__(
        self,
        recorder,
        etl_agent,
        collection_agent,
        repository: IMeetingRepository,
    ) -> None:
        self._recorder = recorder
        self._etl = etl_agent
        self._collector = collection_agent
        self._repository = repository
        self._on_step_complete: Optional[Callable[[PipelineStep], None]] = None

    def on_step_complete(self, callback: Callable[[PipelineStep], None]) -> None:
        self._on_step_complete = callback

    def _emit_step(self, step: PipelineStep) -> None:
        if self._on_step_complete:
            self._on_step_complete(step)

    def run(self, meeting_url: str, title: str = "Reunião") -> PipelineResult:
        """Executa o pipeline completo e retorna o resultado."""
        result = PipelineResult()

        # ── Step 1: Enviar bot ──────────────────────────────────────
        s1 = PipelineStep("enviar_bot", detail="Enviando bot para a reunião...")
        s1.start()
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            session = loop.run_until_complete(self._recorder.join_async(meeting_url))
            loop.close()
            s1.ok(f"Session: {session.id}")
        except Exception as e:
            s1.fail(str(e))
            result.steps = [s1]
            result.error = f"Falha ao enviar bot: {str(e)}"
            return result
        self._emit_step(s1)

        # ── Step 2: Aguardar entrada na reunião ─────────────────────
        s2 = PipelineStep("entrar_reuniao", detail="Aguardando entrar na reunião...")
        s2.start()
        timeout_join = 30
        waited = 0
        while waited < timeout_join:
            if session.status == "recording":
                s2.ok("Bot entrou na reunião")
                break
            if session.status == "error":
                s2.fail(session.error or "Erro ao entrar")
                result.steps = [s1, s2]
                result.error = session.error or "Erro ao entrar na reunião"
                return result
            time.sleep(1)
            waited += 1
        else:
            s2.fail("Timeout ao entrar na reunião")
            result.steps = [s1, s2]
            result.error = "Bot não entrou na reunião em 30s"
            return result
        self._emit_step(s2)

        # ── Step 3: Validar gravação ativa ──────────────────────────
        s3 = PipelineStep("iniciar_gravacao", detail="Validando gravação...")
        s3.start()
        time.sleep(3)
        if session.status == "recording":
            s3.ok("MediaRecorder ativo")
        else:
            s3.fail(f"Status inesperado: {session.status}")
            result.steps = [s1, s2, s3]
            result.error = "Gravação não foi iniciada"
            return result
        self._emit_step(s3)

        # ── Step 4: Aguardar fim da reunião ─────────────────────────
        s4 = PipelineStep("aguardar_reuniao", detail="Aguardando fim da reunião...")
        s4.start()
        # Aguarda o status JSON ser 'done' por polling
        import json, time
        from pathlib import Path
        status_dir = Path(self._recorder.audio_dir) if hasattr(self._recorder, 'audio_dir') else Path("data/audio")
        while True:
            status_path = status_dir / f"bot_session_{session.id}.json"
            if status_path.exists():
                data = json.loads(status_path.read_text(encoding="utf-8"))
                if data["status"] in ("done", "failed"):
                    break
            time.sleep(2)
        if session.status == "done" or (status_path.exists() and json.loads(status_path.read_text(encoding="utf-8")).get("status") == "done"):
            s4.ok("Reunião finalizada")
        else:
            s4.fail(session.error or f"Status final: {session.status}")
            result.steps = [s1, s2, s3, s4]
            result.error = session.error or "Reunião não finalizou corretamente"
            return result
        self._emit_step(s4)

        # ── Step 5: Validar arquivo .webm ───────────────────────────
        s5 = PipelineStep("salvar_audio", detail="Validando arquivo .webm...")
        s5.start()
        audio_path = session.audio_path
        if audio_path and Path(audio_path).exists() and Path(audio_path).stat().st_size > 0:
            result.audio_path = str(audio_path)
            s5.ok(f"{Path(audio_path).stat().st_size} bytes")
        else:
            s5.fail("Arquivo .webm não encontrado ou vazio")
            result.steps = [s1, s2, s3, s4, s5]
            result.error = "Áudio não foi salvo"
            return result
        self._emit_step(s5)

        # ── Step 6: ETL — Transcrever e salvar ─────────────────────
        s6 = PipelineStep("etl_transcrever", detail="Transcrevendo áudio...")
        s6.start()
        try:
            etl_result = self._etl.execute(str(audio_path), title)
            if etl_result.success:
                result.meeting_id = etl_result.meeting_id
                s6.ok(f"Meeting ID: {etl_result.meeting_id}")
            else:
                s6.fail(etl_result.error)
                result.steps = [s1, s2, s3, s4, s5, s6]
                result.error = etl_result.error
                return result
        except Exception as e:
            s6.fail(str(e))
            result.steps = [s1, s2, s3, s4, s5, s6]
            result.error = f"Erro no ETL: {str(e)}"
            return result
        self._emit_step(s6)

        # ── Step 7: Collection — sincronizar com interface ──────────
        s7 = PipelineStep("sincronizar_interface", detail="Sincronizando com interface...")
        s7.start()
        try:
            new_meetings = self._collector.get_new_meetings()
            if any(m.id == result.meeting_id for m in new_meetings):
                s7.ok("Reunião disponível na interface")
            else:
                s7.ok("Reunião salva (interface será atualizada no próximo ciclo)")
        except Exception as e:
            s7.ok(f"Sync agendado (erro não crítico: {str(e)})")
        self._emit_step(s7)

        result.steps = [s1, s2, s3, s4, s5, s6, s7]
        result.success = True
        return result
