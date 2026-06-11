"""
ETL Agent — Extrai, Transforma e Carrega dados de áudio.

Fluxo:
  1. Recebe caminho de arquivo .webm
  2. Envia para WhisperLocal (transcrição)
  3. Cria entidade Meeting com ID único
  4. Salva no MongoDB via repositório
  5. Retorna meeting_id gerado
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from domain.entities.meeting import Meeting
from use_cases.transcribe_meeting import (
    TranscribeMeetingInput,
    TranscribeMeetingUC,
)
from use_cases.summarize_meeting import SummarizeMeetingInput
from interface.llm_services import ILLMService
from repositories.meeting_repository import IMeetingRepository


class ETLAgent:
    """Agente responsável pelo pipeline de ETL: .webm → transcrição → banco."""

    def __init__(
        self,
        transcribe_uc: TranscribeMeetingUC,
        llm: ILLMService,
        repository: IMeetingRepository,
    ) -> None:
        self._transcribe_uc = transcribe_uc
        self._llm = llm
        self._repository = repository

    def execute(self, audio_path: str, title: str = "Reunião") -> ETLResult:
        """Executa o pipeline ETL completo.

        Etapas validadas:
          1. Arquivo .webm existe e tem tamanho > 0
          2. WhisperLocal transcreveu com sucesso
          3. Summary foi gerado
          4. Dados salvos no MongoDB
        """
        steps = []

        # Step 1: validar arquivo de áudio
        path = Path(audio_path)
        if not path.exists():
            return ETLResult(
                success=False, meeting_id="",
                error=f"Arquivo não encontrado: {audio_path}",
                steps=[ETLStep("validar_audio", False, "Arquivo não existe")],
            )
        if path.stat().st_size == 0:
            return ETLResult(
                success=False, meeting_id="",
                error="Arquivo de áudio vazio",
                steps=[ETLStep("validar_audio", False, "Arquivo vazio (0 bytes)")],
            )
        steps.append(ETLStep("validar_audio", True, f"{path.stat().st_size} bytes"))

        # Step 2: transcrever
        meeting_id = str(uuid.uuid4())
        try:
            t_result = self._transcribe_uc.execute(
                TranscribeMeetingInput(audio_path=audio_path, with_diarization=True)
            )
            if not t_result.success:
                return ETLResult(
                    success=False, meeting_id=meeting_id,
                    error=f"Transcrição falhou: {t_result.error_message}",
                    steps=steps + [ETLStep("transcrever", False, t_result.error_message)],
                )
        except Exception as e:
            return ETLResult(
                success=False, meeting_id=meeting_id,
                error=f"Erro na transcrição: {str(e)}",
                steps=steps + [ETLStep("transcrever", False, str(e))],
            )

        steps.append(ETLStep("transcrever", True, f"{len(t_result.transcript.full_text)} chars"))

        # Step 3: criar entidade Meeting
        meeting = Meeting(
            id=meeting_id,
            title=title,
            started_at=datetime.now(),
            audio_path=audio_path,
            transcript_text=t_result.transcript.full_text,
            transcript_formatted=t_result.transcript.formatted,
            participants=t_result.transcript.speakers,
            duration_minutes=t_result.transcript.duration_minutes,
        )

        # Step 4: gerar resumo via LLM
        try:
            s_result = self._llm.summarize(t_result.transcript.full_text)
            if s_result:
                meeting.summary = s_result
        except Exception as e:
            steps.append(ETLStep("sumarizar", False, str(e)))
            # Não é blocker — segue mesmo sem summary
        else:
            steps.append(ETLStep("sumarizar", True, f"{len(meeting.summary.tasks)} tarefas, {len(meeting.summary.decisions)} decisoes"))

        # Step 5: salvar no MongoDB
        try:
            self._repository.save(meeting)
        except Exception as e:
            return ETLResult(
                success=False, meeting_id=meeting_id,
                error=f"Falha ao salvar no banco: {str(e)}",
                steps=steps + [ETLStep("salvar", False, str(e))],
            )

        steps.append(ETLStep("salvar", True, f"ID: {meeting_id}"))

        return ETLResult(success=True, meeting_id=meeting_id, steps=steps)


class ETLStep:
    """Representa uma etapa do pipeline ETL."""

    def __init__(self, name: str, success: bool, detail: str = "") -> None:
        self.name = name
        self.success = success
        self.detail = detail


class ETLResult:
    """Resultado do pipeline ETL."""

    def __init__(
        self,
        success: bool,
        meeting_id: str,
        error: str = "",
        steps: list[ETLStep] | None = None,
    ) -> None:
        self.success = success
        self.meeting_id = meeting_id
        self.error = error
        self.steps = steps or []
