from domain.entities.meeting_type import MeetingType

_FEW_SHOT: dict[MeetingType, str] = {

    MeetingType.PLANNING: """Exemplo de saída para planning:
    {
    "overview": "Sprint 22 planejada com foco em autenticação e melhoria de performance. Time alocou 34 pontos.",
  "topics": ["Autenticação OAuth", "Refatoração do módulo de cache", "Bug crítico #4521"],
  "tasks": [
    {"description": "Implementar login com Google", "responsible": "Ana", "deadline": "Quinta-feira", "estimate": "8 pontos"},
    {"description": "Corrigir bug #4521 no carrinho", "responsible": "Carlos", "deadline": "Amanhã", "estimate": "3 pontos"}
  ],
  "decisions": [
    {"description": "Adiar módulo de relatórios para Sprint 23", "context": "Falta de capacidade no time"}
  ],
  "risks": ["Dependência da API de pagamentos ainda não liberada"]
}
""",
    MeetingType.RETROSPECTIVE: """Exemplo de saída para uma retrospectiva:
{
  "overview": "Time refletiu sobre a sprint com alto engajamento. Principais pontos foram comunicação e qualidade dos testes.",
  "topics": ["Comunicação entre front e back", "Cobertura de testes", "Cerimônias"],
  "went_well": ["Deploy sem incidentes", "Colaboração no pair programming", "Daily objetiva"],
  "to_improve": ["Tickets sem critério de aceite claro", "PR reviews demorados"],
  "action_items": [
    {"description": "Criar template de critério de aceite", "responsible": "Product Owner", "deadline": "Próxima sprint"},
    {"description": "Estabelecer SLA de 24h para PR review", "responsible": "Tech Lead", "deadline": "Essa semana"}
  ],
  "tasks": [],
  "decisions": []
}
""",
    MeetingType.ONE_ON_ONE: """Exemplo de saída para um 1:1:
{
  "overview": "1:1 focado em crescimento de carreira e desafios técnicos atuais.",
  "topics": ["Progressão de carreira", "Projeto X", "Bem-estar"],
  "feedbacks": [
    {"from": "Manager", "to": "Colaborador", "content": "Liderança técnica no último projeto foi excelente"},
    {"from": "Colaborador", "to": "Manager", "content": "Gostaria de mais autonomia nas decisões de arquitetura"}
  ],
  "tasks": [
    {"description": "Criar plano de desenvolvimento individual", "responsible": "Colaborador", "deadline": "Duas semanas"}
  ],
  "decisions": [
    {"description": "Avaliar promoção no próximo ciclo", "context": "Performance consistente nos últimos 2 trimestres"}
  ]
}
""",
    MeetingType.REVIEW: """Exemplo de saída para um review/demo:
{
  "overview": "Sprint 21 entregou 28 dos 34 pontos planejados. Demo bem recebida pelos stakeholders.",
  "topics": ["Demo do módulo de autenticação", "Débito técnico", "Feedbacks dos stakeholders"],
  "delivered": ["Login com Google implementado", "Refatoração do cache concluída"],
  "not_delivered": ["Relatório de exportação — movido para Sprint 22"],
  "stakeholder_feedback": ["Interface de login muito intuitiva", "Solicitar modo escuro para próxima versão"],
  "tasks": [
    {"description": "Adicionar modo escuro", "responsible": "UX", "deadline": "Sprint 22"}
  ],
  "decisions": []
}
""",
    MeetingType.GENERAL: "",
}

_TYPE_INSTRUCTIONS: dict[MeetingType, str] = {
    MeetingType.PLANNING:"""
Foque em:
- Objetivos e metas da sprint/período
- Tarefas com responsável, prazo e estimativa de esforço (se mencionada)
- Dependências entre tarefas
- Riscos identificados pelo time
- Decisões sobre o que foi incluído ou excluído do escopo
Inclua o campo "risks" (lista de strings) e "estimate" em cada tarefa quando mencionado.
""",

    MeetingType.RETROSPECTIVE: """
Foque em:
- O que o time considera que foi bem (went_well)
- O que pode melhorar (to_improve)
- Planos de ação concretos com responsável (action_items)
- Celebrações e conquistas do time
Inclua os campos "went_well" (lista) e "to_improve" (lista) além dos campos padrão.
Use "action_items" em vez de "tasks" para itens de melhoria de processo.
""",

    MeetingType.ONE_ON_ONE: """
Foque em:
- Feedbacks trocados entre as partes (quem deu, para quem, o conteúdo)
- Metas e objetivos pessoais/profissionais discutidos
- Pontos de atenção ou preocupações levantadas
- Compromissos assumidos por cada parte
Inclua o campo "feedbacks" (lista com from, to, content).
Preserve a confidencialidade — não especule sobre intenções não declaradas.
""",

    MeetingType.REVIEW: """
Foque em:
- O que foi entregue vs o que foi planejado
- Conteúdo das demos apresentadas
- Feedbacks dos stakeholders/clientes
- O que não foi entregue e por quê
Inclua "delivered" (lista) e "not_delivered" (lista) e "stakeholder_feedback" (lista).
""",

    MeetingType.INTERVIEW: """
Foque em:
- Experiência e background do candidato mencionados
- Habilidades técnicas demonstradas
- Soft skills observadas
- Pontos fortes e pontos de atenção
- Recomendação geral (se mencionada)
Inclua "strengths", "concerns" e "recommendation" como campos.
Seja factual — registre apenas o que foi explicitamente dito.
""",

    MeetingType.BRAINSTORM: """
Foque em:
- Todas as ideias levantadas (mesmo as descartadas)
- Ideias que geraram mais engajamento ou discussão
- Critérios de priorização usados (se houver)
- Próximos passos de validação ou prototipação
Inclua "ideas" (lista com description e status: "aprovada"/"descartada"/"a validar").
""",

    MeetingType.GENERAL: "",
}


class PromptBuilder:
    """
    Constrói prompts de resumo otimizados por tipo de reunião.
    É uma classe pura — sem dependências externas, fácil de testar.
    O LangChainLLMService recebe uma instância via injeção.

    
    """

    BASE_SYSTEM = """Você é um assistente especializado em analisar reuniões corporativas e Analista de processos 
    processos elaborados pelos stakehoulders .
    Analise a transcrição fornecida e retorne um JSON estruturado.

CONTRATO — REGRAS ABSOLUTAS:
1. RESPONDA APENAS em português do Brasil
2. NÃO alucine — transcreva e analise SOMENTE o que foi efetivamente falado
3. Valide ortografia e gramática do texto gerado (corrija erros óbvios de digitação)
4. Se um campo não puder ser identificado, use lista vazia [] ou string vazia ""
5. Preserve nomes próprios exatamente como aparecem na transcrição
6. Responda APENAS com JSON válido, sem texto antes ou depois
7. Não adicione contexto, interpretação ou suposições, informações falsas — somente fatos da transcrição

Estrutura base (sempre inclua esses campos):
{
  "overview": "parágrafo de 2-3 linhas resumindo propósito e resultado",
  "topics": ["tópico 1", "tópico 2"],
  "tasks": [
    {"description": "...", "responsible": "nome ou Não definido", "deadline": "prazo ou Não definido"}
  ],
  "decisions": [
    {"description": "...", "context": "contexto breve"}
  ]
}
"""

    BASE_CHAT = """Você é um assistente de reuniões. Você participou da reunião abaixo
e pode responder perguntas sobre ela com base exclusivamente no contexto fornecido e realizar Analises de processos junto com o usuario se necessário .

CONTEXTO DA REUNIÃO:
{transcript}

NOTA SOBRE O CONTEXTO: em reuniões longas, o contexto acima pode conter um
RESUMO ESTRUTURADO e apenas os TRECHOS da transcrição relevantes à pergunta,
em vez da transcrição completa. Trechos omitidos aparecem como [...].
Se a resposta não estiver no contexto fornecido, aplique a regra 4 — nunca
deduza o conteúdo dos trechos omitidos.

CONTRATO — REGRAS ABSOLUTAS:
1. Responda SEMPRE em português do Brasil
2. NÃO alucine — responda SOMENTE com base no que foi falado na transcrição
3. Valide ortografia e gramática da sua resposta (corrija erros óbvios)
4. Se a informação não estiver na transcrição, diga exatamente:
   "Isso não foi mencionado durante a reunião."
5. Cite o contexto quando relevante (ex: "Conforme mencionado por [nome]...")
6. Seja direto, objetivo e factual
7. Não adicione opiniões, suposições ou informações externas
8. Se algum segmento da transcrição estiver marcado como não confiável
   (baixa confiança), ignore-o — não o use como base para respostas.

CRIAÇÃO DE TAREFAS:
Quando (e SOMENTE quando) o usuário pedir explicitamente para criar,
registrar ou anotar uma tarefa, inclua ao FINAL da sua resposta um bloco
para cada tarefa solicitada, exatamente neste formato:
---TAREFA---
{{"description": "descrição da tarefa", "responsible": "nome ou Não definido", "deadline": "prazo ou null"}}
---FIM_TAREFA---
Regras das tarefas:
- Nunca crie tarefas que o usuário não pediu para criar
- Use os nomes dos participantes da reunião quando o responsável for citado
- Fora do bloco, confirme em linguagem natural a criação (ex: "Tarefa registrada.")
"""

    def build_summarize_system(self, meeting_type: MeetingType = MeetingType.GENERAL) -> str:
        parts = [self.BASE_SYSTEM]

        instructions = _TYPE_INSTRUCTIONS.get(meeting_type, "")
        if instructions:
            parts.append(f"\nInstruções específicas para {meeting_type.label}:\n{instructions}")

        few_shot = _FEW_SHOT.get(meeting_type, "")
        if few_shot:
            parts.append(f"\n{few_shot}")

        return "\n".join(parts)

    def build_summarize_user(self, transcript: str) -> str:
        return f"TRANSCRIÇÃO:\n\n{transcript}"

    def build_chat_system(self, transcript: str) -> str:
        return self.BASE_CHAT.format(transcript=transcript)

    def get_available_types(self) -> list[MeetingType]:
        return list(MeetingType)