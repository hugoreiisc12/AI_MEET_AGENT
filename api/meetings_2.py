# Importa módulos de utilidade para UUID, caminhos e datetime
import uuid
from pathlib import Path
from datetime import datetime

# Importa FastAPI Router e componentes de upload/tratamento HTTP
from fastapi import APIRouter, UploadFile, File, HTTPException

# Importa schemas de resposta, configurações e container de injeção de dependência
from api.schemas.meeting import UploadResponse, MeetingStatusResponse, ProcessingStatus
from config.settings import get_settings
from presentation.container import get_container

# Cria roteador para endpoints de reuniões
router = APIRouter()
# Obtém configurações da aplicação
settings = get_settings()

# Dicionário em memória para rastrear status de processamento
# Em produção, seria melhor usar Redis ou banco de dados
_status_store: dict[str, ProcessingStatus] = {}


# Endpoint POST que recebe upload de arquivo de áudio
@router.post("/upload", response_model=UploadResponse)
async def upload_meeting(
    file: UploadFile = File(...),  # Arquivo de áudio obrigatório
    title: str = "Reunião sem título",  # Título opcional da reunião
):
    """
    Recebe arquivo de áudio, o salva no disco e enfileira o processamento.
    Retorna o ID da reunião para acompanhar o status.
    """
    # Gera um ID único para a reunião
    meeting_id = str(uuid.uuid4())

    # Prepara o diretório de armazenamento de áudio
    audio_dir = Path(settings.audio_storage_path)
    audio_dir.mkdir(parents=True, exist_ok=True)  # Cria diretório se não existir
    # Extrai extensão do arquivo e constrói caminho de salvamento
    suffix = Path(file.filename or "audio.wav").suffix
    audio_path = str(audio_dir / f"{meeting_id}{suffix}")

    # Salva o arquivo de áudio no disco
    with open(audio_path, "wb") as f:
        f.write(await file.read())

    # Marca o status inicial como pendente
    _status_store[meeting_id] = ProcessingStatus.PENDING

    # Verifica o modo de operação da aplicação
    # Em modo colaborativo, usa Celery para processar assincronamente
    # Em modo solo, processa sincronamente (bloqueante)
    if settings.is_collab:
        # Importa tarefa Celery e enfileira o processamento
        from worker.tasks import process_meeting_task
        process_meeting_task.delay(meeting_id, audio_path, title)
    else:
        # Processa sincronamente (espera terminar antes de retornar)
        _process_sync(meeting_id, audio_path, title)

    # Retorna confirmação do upload com ID para futuro acompanhamento
    return UploadResponse(
        meeting_id=meeting_id,
        status=_status_store[meeting_id],
        message="Áudio recebido. Processamento iniciado.",
    )


# Endpoint GET que retorna o status e dados de uma reunião
@router.get("/{meeting_id}/status", response_model=MeetingStatusResponse)
def get_status(meeting_id: str):
    """
    Retorna o status atual e os dados disponíveis de uma reunião.
    Se ainda está em processamento, retorna status parcial.
    Se já foi processada, retorna dados completos com resumo.
    """
    # Obtém container para acessar repositório
    container = get_container()
    # Busca a reunião pelo ID no repositório
    meeting = container.repository.find_by_id(meeting_id)

    # Se reunião não foi encontrada no repositório
    if not meeting:
        # Tenta obter o status de processamento do store em memória
        status = _status_store.get(meeting_id)
        # Se nem o status está no store, a reunião não existe
        if not status:
            raise HTTPException(404, "Reunião não encontrada")
        # Retorna status parcial enquanto está processando
        return MeetingStatusResponse(
            meeting_id=meeting_id,
            status=status,
            title="Processando...",
            started_at=datetime.now(),
        )

    # Se reunião foi encontrada, retorna dados completos
    return MeetingStatusResponse(
        meeting_id=meeting_id,
        status=ProcessingStatus.DONE,  # Processamento concluído
        title=meeting.title,
        started_at=meeting.started_at,
        duration_minutes=meeting.duration_minutes,
        participants=meeting.participants,
        # Mapeia resumo para schema se disponível
        summary=_map_summary(meeting.summary) if meeting.summary else None,
    )


# Endpoint GET que lista todas as reuniões processadas
@router.get("/", response_model=list[MeetingStatusResponse])
def list_meetings():
    """
    Retorna uma lista com todas as reuniões processadas e disponíveis.
    Útil para exibir histórico de reuniões do usuário.
    """
    # Obtém container para acessar repositório
    container = get_container()
    # Busca todas as reuniões armazenadas
    meetings = container.repository.list_all()
    # Converte cada reunião para schema de resposta
    return [
        MeetingStatusResponse(
            meeting_id=m.id,
            status=ProcessingStatus.DONE,  # Todas as listadas foram processadas
            title=m.title,
            started_at=m.started_at,
            duration_minutes=m.duration_minutes,
            participants=m.participants,
        )
        for m in meetings
    ]


# Função auxiliar para processar reunião sincronamente (modo solo)
def _process_sync(meeting_id: str, audio_path: str, title: str) -> None:
    """
    Processa uma reunião de forma síncrona (bloqueante).
    Usado no modo solo quando não há Celery disponível.
    
    Fluxo:
    1. Transcreve o áudio
    2. Gera resumo a partir da transcrição
    3. Atualiza status durante o processamento
    """
    # Importa entidades e casos de uso necessários
    from domain.entities.meeting import Meeting
    from use_cases.transcribe_meeting import TranscribeMeetingInput
    from use_cases.summarize_meeting import SummarizeMeetingInput

    # Obtém container com dependências
    container = get_container()
    # Marca status como "transcrevendo"
    _status_store[meeting_id] = ProcessingStatus.TRANSCRIBING

    # Executa transcrição do áudio com identificação de speakers
    t_result = container.transcribe_meeting.execute(
        TranscribeMeetingInput(audio_path=audio_path, with_diarization=True)
    )
    # Se transcrição falhar, marca como erro e retorna
    if not t_result.success:
        _status_store[meeting_id] = ProcessingStatus.ERROR
        return

    # Cria entidade Meeting com dados da transcrição
    meeting = Meeting(
        id=meeting_id, 
        title=title,
        started_at=datetime.now(),
        audio_path=audio_path,
        transcript_text=t_result.transcript.full_text,  # Texto puro
        transcript_formatted=t_result.transcript.formatted,  # Texto com timestamps
        participants=t_result.transcript.speakers,  # Speakers identificados
        duration_minutes=t_result.transcript.duration_minutes,  # Duração em minutos
    )

    # Marca status como "gerando resumo"
    _status_store[meeting_id] = ProcessingStatus.SUMMARIZING
    # Executa geração de resumo usando IA
    s_result = container.summarize_meeting.execute(
        SummarizeMeetingInput(meeting=meeting)
    )
    # Marca status final: DONE se sucesso, ERROR se falha
    _status_store[meeting_id] = (
        ProcessingStatus.DONE if s_result.success else ProcessingStatus.ERROR
    )


# Função auxiliar para converter objeto Summary em schema Pydantic
def _map_summary(summary):
    """
    Converte objeto Summary do domínio para schema Pydantic de resposta.
    Realiza mapeamento de atributos e conversão de listas.
    """
    # Importa schemas Pydantic para resposta
    from api.schemas.meeting import SummarySchema, TaskSchema, DecisionSchema
    # Cria schema com dados mapeados
    return SummarySchema(
        overview=summary.overview,  # Resumo geral
        topics=summary.topics,  # Lista de tópicos já é compatível
        # Mapeia cada tarefa do domínio para schema
        tasks=[TaskSchema(
            description=t.description, 
            responsible=t.responsible,
            deadline=t.deadline, 
            done=t.done
        ) for t in summary.tasks],
        # Mapeia cada decisão do domínio para schema
        decisions=[DecisionSchema(
            description=d.description, 
            context=d.context
        ) for d in summary.decisions],
    )