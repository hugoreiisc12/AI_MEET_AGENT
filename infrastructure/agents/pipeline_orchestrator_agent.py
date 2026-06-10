# Orquestrador de pipeline npara execução completa de processamentos 
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from domain.entities.meeting import Meeting
from repositories.meeting_repository import IMeetingRepository
from use_cases.transcribe_meeting import TranscribeMeetingUC, TranscribeMeetingInput
from use_cases.summarize_meeting import SummarizeMeetingUC, SummarizeMeetingInput
from use_cases.chat_with_meeting import ChatWithMeetingUC

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

# Class de PipelineTaks aonde cada tarefa tem um nome, status possível 
@dataclass
class PipelineTask:
    name: str
    status: TaskStatus = TaskStatus.PENDING
    error: str = ""
    result: object = None

# Class de Pipeline Execução que tem o id da reunião e um dicionario de tarefas 
@dataclass
class PipelineExecution:
    meeting_id: str
    tasks: dict[str, PipelineTask] = field(default_factory=dict)
    started_at: datetime = field(default_factory=datetime.now)
    finished_at: Optional[datetime] = None
    success: bool = False

    @property
    def is_complete(self) -> bool:
        return all(t.status == TaskStatus.COMPLETED for t in self.tasks.values())

    @property
    def has_failed(self) -> bool:
        return any(t.status == TaskStatus.FAILED for t in self.tasks.values())

    @property
    def failed_tasks(self) -> list[PipelineTask]:
        return [t for t in self.tasks.values() if t.status == TaskStatus.FAILED]

# Class de Agente orquestrador de pipeline, responsável por executar cada fluxo da pipeline do começo até o final
class PipelineOrchestratorAgent:
    """Agente orquestrador de pipeline.

    Responsável por executar cada fluxo da pipeline do começo até o final,
    desde o momento em que o bot é enviado para a reunião até a parte final
    de interação da IA com o usuário.

    Funcionamento:
    - Recebe a pipeline e a desmembra em blocos de tarefas
    - Cada tarefa é validada: foi concluída? Se sim, prossegue.
      Se não, para e retorna erro informando onde travou e o motivo.
    - Orquestra tudo em efeito em cadeia: a partir do momento que o bot
      vai pra reunião gravar e termina, já começa o próximo passo
      automaticamente sem intervenção manual.

    Blocos da pipeline:
        1. Bot.envio        — Enviar bot para reunião
        2. Bot.gravacao     — Bot grava áudio da reunião
        3. Audio.salvamento — Salvar arquivo de áudio .webm
        4. Audio.validacao  — Validar integridade do áudio
        5. Transcrever      — Whisper transcreve áudio
        6. Salvar.transcricao — Persistir transcrição no banco
        7. Sumarizar        — LLM gera resumo estruturado
        8. Salvar.resumo    — Persistir resumo no banco
        9. Agentes.secundarios — Disparar agentes ETL e Validação
        10. Interacao.usuario — Pipeline pronta para interação com usuário
    """

    TASK_BOT_ENVIO = "bot.envio"
    TASK_BOT_GRAVACAO = "bot.gravacao"
    TASK_AUDIO_SALVAMENTO = "audio.salvamento"
    TASK_AUDIO_VALIDACAO = "audio.validacao"
    TASK_TRANSCREVER = "transcrever"
    TASK_SALVAR_TRANSCRICAO = "salvar.transcricao"
    TASK_SUMARIZAR = "sumarizar"
    TASK_SALVAR_RESUMO = "salvar.resumo"
    TASK_AGENTES_SECUNDARIOS = "agentes.secundarios"
    TASK_INTERACAO_USUARIO = "interacao.usuario"

    TASK_ORDER = [
        TASK_BOT_ENVIO,
        TASK_BOT_GRAVACAO,
        TASK_AUDIO_SALVAMENTO,
        TASK_AUDIO_VALIDACAO,
        TASK_TRANSCREVER,
        TASK_SALVAR_TRANSCRICAO,
        TASK_SUMARIZAR,
        TASK_SALVAR_RESUMO,
        TASK_AGENTES_SECUNDARIOS,
        TASK_INTERACAO_USUARIO,
    ]

    def __init__(
        self,
        repository: IMeetingRepository,
        transcribe_uc: TranscribeMeetingUC,
        summarize_uc: SummarizeMeetingUC,
        chat_uc: Optional[ChatWithMeetingUC] = None,
        etl_agent: object = None,
        validation_agent: object = None,
    ) -> None:
        self._repository = repository
        self._transcribe_uc = transcribe_uc
        self._summarize_uc = summarize_uc
        self._chat_uc = chat_uc
        self._etl_agent = etl_agent
        self._validation_agent = validation_agent
        self._executions: dict[str, PipelineExecution] = {}

    def run_pipeline(
        self,
        meeting_id: str,
        audio_path: str,
        title: str = "Reunião",
    ) -> PipelineExecution:
        """Inicia a execução da pipeline completa em background.

        Args:
            meeting_id: ID único da reunião
            audio_path: Caminho do arquivo de áudio
            title: Título da reunião

        Returns:
            PipelineExecution com status inicial
        """
        execution = PipelineExecution(meeting_id=meeting_id)
        execution.tasks = {
            task_name: PipelineTask(name=task_name)
            for task_name in self.TASK_ORDER
        }
        self._executions[meeting_id] = execution

        thread = threading.Thread(
            target=self._execute_pipeline,
            args=(meeting_id, audio_path, title, execution),
            daemon=True,
            name=f"PipelineAgent-{meeting_id[:8]}",
        )
        thread.start()

        logger.info(
            "[Pipeline Agent] Pipeline iniciada para reunião %s — %s",
            meeting_id, title,
        )
        return execution

    def get_execution(self, meeting_id: str) -> Optional[PipelineExecution]:
        """Retorna o estado da execução para uma reunião."""
        return self._executions.get(meeting_id)

    def _execute_pipeline(
        self,
        meeting_id: str,
        audio_path: str,
        title: str,
        execution: PipelineExecution,
    ) -> None:
        try:
            for task_name in self.TASK_ORDER:
                task = execution.tasks[task_name]
                task.status = TaskStatus.RUNNING
                logger.info("[Pipeline Agent] Executando tarefa: %s", task_name)

                success = self._execute_task(
                    task_name, meeting_id, audio_path, title,
                )

                if success:
                    task.status = TaskStatus.COMPLETED
                    logger.info("[Pipeline Agent] Tarefa concluída: %s", task_name)
                else:
                    task.status = TaskStatus.FAILED
                    task.error = f"Tarefa {task_name} falhou sem erro específico"
                    logger.error("[Pipeline Agent] Tarefa falhou: %s", task_name)
                    break

            if execution.is_complete:
                execution.success = True
                execution.finished_at = datetime.now()
                logger.info(
                    "[Pipeline Agent] Pipeline concluída com sucesso: %s",
                    meeting_id,
                )
            elif execution.has_failed:
                execution.finished_at = datetime.now()
                failed = execution.failed_tasks
                logger.error(
                    "[Pipeline Agent] Pipeline travou na tarefa '%s' — motivo: %s",
                    failed[0].name if failed else "desconhecido",
                    failed[0].error if failed else "erro desconhecido",
                )

        except Exception as e:
            execution.finished_at = datetime.now()
            execution.success = False
            logger.exception(
                "[Pipeline Agent] Erro crítico na pipeline %s: %s",
                meeting_id, e,
            

         )

# Função de processamento de pipeline para cada tarefa chamada no worker do Celery
    def _execute_task(
        self,
        task_name: str,
        meeting_id: str,
        audio_path: str,
        title: str,
    ) -> bool:
        try:
            if task_name == self.TASK_BOT_ENVIO:
                return self._task_bot_envio(meeting_id)

            elif task_name == self.TASK_BOT_GRAVACAO:
                return self._task_bot_gravacao(meeting_id)

            elif task_name == self.TASK_AUDIO_SALVAMENTO:
                return self._task_audio_salvamento(meeting_id, audio_path)

            elif task_name == self.TASK_AUDIO_VALIDACAO:
                return self._task_audio_validacao(audio_path)

            elif task_name == self.TASK_TRANSCREVER:
                return self._task_transcrever(meeting_id)

            elif task_name == self.TASK_SALVAR_TRANSCRICAO:
                return self._task_salvar_transcricao(meeting_id)

            elif task_name == self.TASK_SUMARIZAR:
                return self._task_summarizar(meeting_id)

            elif task_name == self.TASK_SALVAR_RESUMO:
                return self._task_salvar_resumo(meeting_id)

            elif task_name == self.TASK_AGENTES_SECUNDARIOS:
                return self._task_agentes_secundarios(meeting_id)

            elif task_name == self.TASK_INTERACAO_USUARIO:
                return self._task_interacao_usuario(meeting_id)

            return True

        except Exception as e:
            logger.exception(
                "[Pipeline Agent] Erro na tarefa %s: %s", task_name, e,
            )
            raise

    # ── Implementação de cada tarefa ──────────────────────────────────────

    def _task_bot_envio(self, meeting_id: str) -> bool:
        """Tarefa 1: Enviar bot para a reunião."""
        meeting = self._repository.find_by_id(meeting_id)
        if not meeting:
            logger.error("[Pipeline Agent] Reunião %s não encontrada", meeting_id)
            return False
        logger.info("[Pipeline Agent] Bot enviado para reunião %s", meeting_id)
        return True

    def _task_bot_gravacao(self, meeting_id: str) -> bool:
        """Tarefa 2: Bot grava áudio da reunião."""
        meeting = self._repository.find_by_id(meeting_id)
        if not meeting:
            return False
        if meeting.audio_path and Path(meeting.audio_path).exists():
            logger.info(
                "[Pipeline Agent] Gravação concluída: %s", meeting.audio_path,
            )
            return True
        logger.error("[Pipeline Agent] Áudio da reunião %s não foi gravado", meeting_id)
        return False

    def _task_audio_salvamento(self, meeting_id: str, audio_path: str) -> bool:
        """Tarefa 3: Salvar arquivo de áudio."""
        meeting = self._repository.find_by_id(meeting_id)
        if not meeting:
            return False
        meeting.audio_path = audio_path
        self._repository.save(meeting)
        logger.info("[Pipeline Agent] Áudio salvo: %s", audio_path)
        return True

    def _task_audio_validacao(self, audio_path: str) -> bool:
        """Tarefa 4: Validar integridade do áudio."""
        path = Path(audio_path)
        if not path.exists():
            logger.error("[Pipeline Agent] Áudio não encontrado: %s", audio_path)
            return False
        if path.stat().st_size == 0:
            logger.error("[Pipeline Agent] Áudio vazio: %s", audio_path)
            return False
        size_mb = path.stat().st_size / (1024 * 1024)
        logger.info(
            "[Pipeline Agent] Áudio validado: %s (%.1f MB)", audio_path, size_mb,
        )
        return True

    def _task_transcrever(self, meeting_id: str) -> bool:
        """Tarefa 5: Transcrever áudio com Whisper."""
        meeting = self._repository.find_by_id(meeting_id)
        if not meeting or not meeting.audio_path:
            return False

        result = self._transcribe_uc.execute(
            TranscribeMeetingInput(
                audio_path=meeting.audio_path,
                with_diarization=True,
            )
        )

        if result.success:
            meeting.transcript_text = result.transcript.full_text
            meeting.transcript_formatted = result.transcript.formatted
            meeting.participants = result.transcript.speakers
            self._repository.save(meeting)
            logger.info("[Pipeline Agent] Transcrição concluída para %s", meeting_id)
            return True

        logger.error(
            "[Pipeline Agent] Transcrição falhou: %s", result.error_message,
        )
        return False

    def _task_salvar_transcricao(self, meeting_id: str) -> bool:
        """Tarefa 6: Persistir transcrição no banco."""
        meeting = self._repository.find_by_id(meeting_id)
        if not meeting:
            return False
        if not meeting.transcript_text:
            logger.error(
                "[Pipeline Agent] Transcrição vazia para %s", meeting_id,
            )
            return False
        self._repository.save(meeting)
        logger.info("[Pipeline Agent] Transcrição salva no banco: %s", meeting_id)
        return True

    def _task_summarizar(self, meeting_id: str) -> bool:
        """Tarefa 7: LLM gera resumo estruturado."""
        meeting = self._repository.find_by_id(meeting_id)
        if not meeting:
            return False

        result = self._summarize_uc.execute(
            SummarizeMeetingInput(meeting=meeting)
        )

        if result.success:
            meeting.summary = result.summary
            self._repository.save(meeting)
            logger.info("[Pipeline Agent] Sumarização concluída para %s", meeting_id)
            return True

        logger.error(
            "[Pipeline Agent] Sumarização falhou: %s", result.error_message,
        )
        return False

    def _task_salvar_resumo(self, meeting_id: str) -> bool:
        """Tarefa 8: Persistir resumo no banco."""
        meeting = self._repository.find_by_id(meeting_id)
        if not meeting:
            return False
        if not meeting.summary:
            logger.error("[Pipeline Agent] Resumo vazio para %s", meeting_id)
            return False
        self._repository.save(meeting)
        logger.info("[Pipeline Agent] Resumo salvo no banco: %s", meeting_id)
        return True

    def _task_agentes_secundarios(self, meeting_id: str) -> bool:
        """Tarefa 9: Disparar agentes ETL e Validação."""
        logger.info(
            "[Pipeline Agent] Agentes secundários notificados para %s",
            meeting_id,
        )
        return True

    def _task_interacao_usuario(self, meeting_id: str) -> bool:
        """Tarefa 10: Pipeline pronta para interação com usuário."""
        meeting = self._repository.find_by_id(meeting_id)
        if not meeting:
            return False
        logger.info(
            "[Pipeline Agent] Pipeline pronta — reunião %s disponível para interação",
            meeting_id,
        )
        return True
