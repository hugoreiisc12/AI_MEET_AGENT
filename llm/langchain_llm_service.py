# Implementando serviços de LLM usando LangChain + OpenAI para processamento de reuniões 
import json
from langchain_openai import ChatOpenAI
from langchain.memory import ConversationBufferMemory
from langchain.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
from langchain.schema import HumanMessage, SystemMessage
 
from entities.metting import Summary, Task, Decision  # CORRIGIDO: domain.entities → entities
from interface.llm_services import ILLMService, LLMServiceError  # CORRIGIDO: domain.interfaces → interface
from config.settings import get_settings

# Prompts (separados do código para facilitar ajuste sem tocar na lógica)

SUMMARIZE_SYSTEM_PROMPT = """ Voce é um assistente de IA especializado em resumir reuniões corporativas

Analise a trasncrição fornecida e retorne um JSON com exatamente esta estrutura:

{
   "overview": "Paragrafo de 2-3 linhas resumindo o proposito e resultado geral da reunião",
   "topics": ["Topico 1", "Topico 2", "..."],
   "tasks": [
    {
        "description": "Descrição com detalhes da tarefa",
        "responsible": "Nome ou 'Não definido'",
        "deadline": "Prazo mencionado ou 'Não definido'"
        }
    ],
    "decisions": [
    {
      "description": "Descrição da tomada de decisão",
      "context": "Contexto do que e porque foi definido"
      }
    ]
} 
Regras: 
- Responda APENAS com um JSON, sem texto antes ou depois 
- Se um campo não for identificado na transição, use a lista vazia [] ou string vazia ""
- Extraia apenas o que está explicitamente na transcrição, não invente 
- Escreva em portugues Brasil
"""
# Prompt para chat, que instrui a LLM a responder perguntas sobre a reunião com base na transcrição e a manter um historico de conversa para contexto adicional 
CHAT_SYSTEM_PROMPT = """Você é um assistente de reuniões. Você participou da reunião abaixo e pode
responder perguntas sobre ela com base na transcrição.

TRANSCRIÇÃO DA REUNIÃO:
{transcript}

Regras:
- Responda sempre em português Brasil
- Se a informação não tiver na transcrição, responda claramente "Isso não foi mencionado na reunião"
- Seja direto e objetivo
- Quando citar algo da reunião, diga o contexto (ex: "Conforme mencionado por Speaker 0...")"""  

# Definindo a classe de service a LLM usando LangChain + OpenAI, 
# que implementa a interface ILLMService e encapsula a lógica de chamada de LLM para summariação
class LangChainLLMService(ILLMService):
    """ Implementação de ILMService usando LangChain + GPT-4o

    Responsabilidades:
    - Summarize: chama a LLM com prompt estruturado, parseia JSON -> Summary
    - Chat: mantém historico de conversa por sessão via ConversationBufferMemory
    """
# Metodo construtor que recebe o cliente OpenAI, via injeção de dependência ou cria um novo se não for fornecido
    def __init__(self, llm: ChatOpenAI | None = None) -> None:  
        settings = get_settings()
        self._llm = llm or ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            temperature=0.2,  # Baixo para respostas consistentes e objetivas
        )  
        # Memoria por instância - uma instância por sessão de reunião
        self.memory = ConversationBufferMemory(
            return_messages=True,
            human_prefix="Usuário",
            ai_prefix="Assistente",
        )
        self._current_transcript: str = ""
  
  # Metodo de sumarização, que chama a LLM com prompt estruturado,
  # parseia o JSON retornando e converte na entity Summary do domain
    def chat(self, question: str, context: str, history: list[dict]) -> str:
        """
        Responde uma pergunta sobre reunião com base na transcrição e historico de conversa.

        Args:
            question: Pergunta do usuário
            context: Transcrição completa
            history: [{"role": "user"|"assistant", "content": str}]
        """
        try:
            # Monta mensagens: system com transcrição + historico + pergunta atual
            messages = [
                SystemMessage(content=CHAT_SYSTEM_PROMPT.format(transcript=context))  
            ]
            for turn in history:
                if turn["role"] == "user":
                    messages.append(HumanMessage(content=turn["content"]))  
                else:
                    from langchain.schema import AIMessage
                    messages.append(AIMessage(content=turn["content"]))  
            messages.append(HumanMessage(content=question))

            response = self._llm(messages)  
            return response.content

        except Exception as e:
            raise LLMServiceError(f"Falha no chat: {str(e)}") from e

# Metodo de chat, que chama a LLM com prompt estrutuado e parseia o JSON retornando, 
# para coverter na entity summary JSON e tratamento de erros específicos relacionados a LLM 
    def _parse_summary(self, raw: str) -> Summary:
        """
        Converte o JSON retornado pelo LLM na entity Summary.
        Robusto a variações: remove markdown fences se o LLM as incluir.
        """
        try:
            cleaned = raw.strip()
            # CORRIGIDO: Remove ```json ... ``` se o LLM incluir mesmo com instrução contrária
            if cleaned.startswith("```json"):  
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):  
                    cleaned = cleaned.split("```")[1]
            cleaned = cleaned.strip()

            data: dict = json.loads(cleaned)

            tasks = [  
                Task(
                    description=t.get("description", ""),
                    responsible=t.get("responsible", "Não definido"),
                    deadline=t.get("deadline", "Não definido"),
                )
                for t in data.get("tasks", [])
            ]

            decisions = [  
                Decision(
                    description=d.get("description", ""),
                    context=d.get("context", ""),
                )
                for d in data.get("decisions", [])
            ]

            return Summary(  
                overview=data.get("overview", ""),
                topics=data.get("topics", []),
                tasks=tasks,
                decisions=decisions,
            )
        except (json.JSONDecodeError, KeyError) as e: 
            raise LLMServiceError(
                f"LLM retornou JSON inválido: {str(e)}\nResposta bruta: {raw[:300]}"
            ) from e
 