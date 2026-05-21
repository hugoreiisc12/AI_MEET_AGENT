# Implementação de LLM service usando LangChain + OpenAI para processamento de reuniões
import json
import logging
import time
from typing import Optional
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, BaseMessage
from pydantic import SecretStr

from domain.entities.meeting import Summary, Task, Decision
from domain.entities.meeting_type import MeetingType
from interface.llm_services import ILLMService, LLMServiceError
from config.settings import get_settings
from infrastructure.llm.prompt_builder import PromptBuilder

# Logger para monitoramento e debug
logger = logging.getLogger(__name__)

# Prompt para chat: instrui LLM a responder perguntas sobre reunião
CHAT_SYSTEM_PROMPT = """Você é um assistente de reuniões. Você participou da reunião abaixo e pode responder perguntas sobre ela.

TRANSCRIÇÃO DA REUNIÃO:
{transcript}

Regras:
- Responda sempre em português Brasil
- Se a informação não tiver na transcrição, responda "Isso não foi mencionado na reunião"
- Seja direto e objetivo
- Cite a fonte quando possível (ex: "Conforme mencionado por Speaker 0...")"""


# Implementação de ILLMService usando LangChain + GPT-4o
class LangChainLLMService(ILLMService):
    """Serviço de LLM com LangChain orquestrando chamadas OpenAI com retry e validação.
    
    Características:
    - Retry automático com backoff exponencial
    - Validação de entrada
    - Logging completo
    - Suporte a múltiplos tipos de reunião
    - Tratamento robusto de erros JSON
    """

    # Constantes de configuração
    MAX_RETRIES = 3
    INITIAL_RETRY_DELAY = 1.0  # segundos
    BACKOFF_FACTOR = 2.0
    MAX_TRANSCRIPT_LENGTH = 50000  # caracteres

    def __init__(
        self,
        llm: Optional[ChatOpenAI] = None,
        temperature: float = 0.2,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        """Inicializa o serviço LLM.
        
        Args:
            llm: Instância ChatOpenAI customizada (opcional)
            temperature: Temperatura para geração (0.0-1.0). Padrão 0.2 para consistência
            max_retries: Máximo de tentativas de retry (padrão 3)
        """
        settings = get_settings()
        self._llm = llm or ChatOpenAI(
            model=settings.openai_model,
            api_key=SecretStr(settings.openai_api_key),
            temperature=temperature,
            timeout=60,  # timeout de 60 segundos
            max_retries=max_retries,
        )
        self._temperature = temperature
        self._max_retries = max_retries
        logger.info(f"LangChainLLMService inicializado com temperatura={temperature}, max_retries={max_retries}")

    def summarize(
        self,
        transcript: str,
        meeting_type: MeetingType = MeetingType.GENERAL,
    ) -> Summary:
        """Analisa transcrição e retorna Summary com tópicos, tarefas, decisões.
        
        Args:
            transcript: Texto completo da transcrição
            meeting_type: Tipo de reunião (GENERAL, PLANNING, RETROSPECTIVE, etc)
        
        Returns:
            Summary com overview, topics, tasks e decisions
        
        Raises:
            LLMServiceError: Se falhar após todas as tentativas
        """
        # Validação de entrada
        if not transcript or not transcript.strip():
            logger.warning("Transcrição vazia recebida")
            raise LLMServiceError("Transcrição não pode estar vazia")
        
        if len(transcript) > self.MAX_TRANSCRIPT_LENGTH:
            logger.warning(f"Transcrição muito longa ({len(transcript)} chars), truncando")
            transcript = transcript[:self.MAX_TRANSCRIPT_LENGTH]
        
        logger.info(f"Iniciando sumarização para tipo: {meeting_type.label}")
        
        try:
            builder = PromptBuilder()
            system_prompt = builder.build_summarize_system(meeting_type)
            user_message = builder.build_summarize_user(transcript)
            
            messages: list[BaseMessage] = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_message),
            ]
            
            # Executa com retry
            response = self._invoke_with_retry(messages, "sumarização")
            
            if not response.content:
                logger.error("Resposta vazia da LLM para sumarização")
                raise LLMServiceError("Resposta vazia da LLM")
            
            content = response.content if isinstance(response.content, str) else str(response.content)
            summary = self._parse_summary(content)
            
            logger.info(f"Sumarização concluída: {len(summary.topics)} tópicos, {len(summary.tasks)} tarefas")
            return summary
            
        except LLMServiceError:
            raise
        except Exception as e:
            logger.exception(f"Erro inesperado na sumarização")
            raise LLMServiceError(f"Falha na sumarização: {str(e)}") from e

    def chat(
        self,
        question: str,
        context: str,
        history: list[dict],
    ) -> str:
        """Responde pergunta sobre reunião mantendo contexto de conversa.
        
        Args:
            question: Pergunta do usuário
            context: Transcrição completa da reunião
            history: Histórico de conversa anterior (formato: [{"role": "user|assistant", "content": "..."}])
        
        Returns:
            Resposta do assistente
        
        Raises:
            LLMServiceError: Se falhar após todas as tentativas
        """
        # Validação de entrada
        if not question or not question.strip():
            raise LLMServiceError("Pergunta não pode estar vazia")
        
        if not context or not context.strip():
            raise LLMServiceError("Contexto da reunião não pode estar vazio")
        
        if not isinstance(history, list):
            logger.warning("Histórico inválido, inicializando como lista vazia")
            history = []
        
        logger.info(f"Respondendo pergunta: {question[:50]}... com {len(history)} turnos de histórico")
        
        try:
            # Monta mensagens: system com transcrição + histórico + pergunta
            messages: list[BaseMessage] = [
                SystemMessage(content=CHAT_SYSTEM_PROMPT.format(transcript=context))
            ]
            
            for turn in history:
                role = turn.get("role", "user")
                content = turn.get("content", "")
                
                if not content:
                    continue
                
                if role == "user":
                    messages.append(HumanMessage(content=content))
                elif role == "assistant":
                    messages.append(AIMessage(content=content))
            
            messages.append(HumanMessage(content=question))
            
            # Executa com retry
            response = self._invoke_with_retry(messages, "chat")
            
            if not response.content:
                logger.warning("Resposta vazia para pergunta")
                return "Desculpe, não consegui processar sua pergunta. Tente novamente."
            
            content = response.content if isinstance(response.content, str) else str(response.content)
            logger.debug(f"Resposta gerada: {len(content)} caracteres")
            
            return content
            
        except LLMServiceError:
            raise
        except Exception as e:
            logger.exception(f"Erro inesperado no chat")
            raise LLMServiceError(f"Falha no chat: {str(e)}") from e

    def _invoke_with_retry(
        self,
        messages: list[BaseMessage],
        operation: str,
    ) -> BaseMessage:
        """Invoca LLM com retry automático e backoff exponencial.
        
        Args:
            messages: Lista de mensagens para enviar
            operation: Nome da operação (para logging)
        
        Returns:
            Resposta da LLM
        
        Raises:
            LLMServiceError: Se todas as tentativas falharem
        """
        last_error = None
        retry_delay = self.INITIAL_RETRY_DELAY
        
        for attempt in range(1, self._max_retries + 1):
            try:
                logger.debug(f"Tentativa {attempt}/{self._max_retries} para {operation}")
                response = self._llm.invoke(messages)
                
                if response is None:
                    raise LLMServiceError("Resposta None da LLM")
                
                logger.debug(f"Sucesso na {operation} na tentativa {attempt}")
                return response
                
            except Exception as e:
                last_error = e
                logger.warning(
                    f"Falha na tentativa {attempt}/{self._max_retries} para {operation}: {str(e)}"
                )
                
                if attempt < self._max_retries:
                    logger.info(f"Aguardando {retry_delay}s antes de retry...")
                    time.sleep(retry_delay)
                    retry_delay *= self.BACKOFF_FACTOR
        
        logger.error(f"Falha após {self._max_retries} tentativas para {operation}")
        raise LLMServiceError(
            f"Falha na {operation} após {self._max_retries} tentativas: {str(last_error)}"
        ) from last_error

    def _parse_summary(self, raw: str) -> Summary:
        """Parseia JSON da LLM com tratamento robusto de formatação.
        
        Handles:
        - Markdown code fences (```json ... ```)
        - Extra whitespace e newlines
        - Valores faltantes
        
        Args:
            raw: String JSON bruto da LLM
        
        Returns:
            Summary parseado
        
        Raises:
            LLMServiceError: Se JSON for inválido
        """
        if not raw or not raw.strip():
            raise LLMServiceError("Resposta vazia não pode ser parseada")
        
        try:
            cleaned = raw.strip()
            logger.debug(f"Limpando JSON (length: {len(cleaned)})")
            
            # Remove markdown code fences
            if cleaned.startswith("```"):
                # Remove abertura ```json ou ```
                lines = cleaned.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                
                # Remove fechamento ```
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                
                cleaned = "\n".join(lines).strip()
            
            logger.debug(f"JSON após limpeza (length: {len(cleaned)})")
            
            # Parse JSON
            data: dict = json.loads(cleaned)
            
            # Validação mínima
            if not isinstance(data, dict):
                raise ValueError("Root deve ser um objeto JSON")
            
            # Parse tasks
            tasks_raw = data.get("tasks", [])
            if not isinstance(tasks_raw, list):
                logger.warning("Tasks não é lista, usando vazio")
                tasks_raw = []
            
            tasks = [
                Task(
                    description=str(t.get("description", "")).strip() or "Sem descrição",
                    responsible=str(t.get("responsible", "Não definido")).strip() or "Não definido",
                    deadline=str(t.get("deadline", "Não definido")).strip() or "Não definido",
                )
                for t in tasks_raw
                if isinstance(t, dict)
            ]
            
            # Parse decisions
            decisions_raw = data.get("decisions", [])
            if not isinstance(decisions_raw, list):
                logger.warning("Decisions não é lista, usando vazio")
                decisions_raw = []
            
            decisions = [
                Decision(
                    description=str(d.get("description", "")).strip() or "Sem descrição",
                    context=str(d.get("context", "")).strip() or "Sem contexto",
                )
                for d in decisions_raw
                if isinstance(d, dict)
            ]
            
            # Parse topics
            topics_raw = data.get("topics", [])
            if not isinstance(topics_raw, list):
                logger.warning("Topics não é lista, usando vazio")
                topics_raw = []
            
            topics = [str(t).strip() for t in topics_raw if t]
            
            summary = Summary(
                overview=str(data.get("overview", "")).strip() or "Sem overview",
                topics=topics,
                tasks=tasks,
                decisions=decisions,
            )
            
            logger.info(f"Summary parseado com sucesso: {len(topics)} tópicos, {len(tasks)} tasks, {len(decisions)} decisions")
            return summary
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON inválido: {str(e)}")
            logger.error(f"Raw response preview: {raw[:200]}")
            raise LLMServiceError(
                f"JSON inválido da LLM: {str(e)}\nPrimeiros 200 chars: {raw[:200]}"
            ) from e
        except (ValueError, KeyError, AttributeError) as e:
            logger.error(f"Erro ao processar dados JSON: {str(e)}")
            raise LLMServiceError(
                f"Erro ao processar resposta JSON: {str(e)}"
            ) from e