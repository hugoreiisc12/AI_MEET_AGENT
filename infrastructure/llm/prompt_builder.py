"""infraestrutura para construção de prompts para o LLM (promptBuilder.py).

Conéstruoi prompts de resumo otimizados por tipo de reunião.

Principíos:
- Few-shot learning examples: cada tipo de reunião tem uma tipo de saída esperada
- Instruções específicas: o que enfatizar em cada tipo
- Formato consistente: sempre JSON estruturado para facilitar o parsing confiável
- Testável: PromptBuilder é uma classe pura, sem chamadas externas
"""

from domain.entities.meeting_type import MeetingType

# Few-shot exemplos por tipo
# Cada exemplo mostra a LLM o formato e nívelde detalhe esperado

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
    MeetingType.GENERAL: "",  # sem few-shot — prompt padrão já é suficiente
}

# Instruções específicas por tipo
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


# ── PromptBuilder ─────────────────────────────────────────────────────────
# Classe responsável por construir os prompts de system e user para o processo de sumarização e chat
class PromptBuilder:
    """
    Constrói prompts de resumo otimizados por tipo de reunião.

    É uma classe pura — sem dependências externas, fácil de testar.
    O LangChainLLMService recebe uma instância via injeção.
    """

    BASE_SYSTEM = """Você é um assistente especializado em analisar reuniões corporativas.
Analise a transcrição fornecida e retorne um JSON estruturado.

Regras absolutas:
- Responda APENAS com JSON válido, sem texto antes ou depois
- Não invente informações que não estão na transcrição
- Se um campo não puder ser identificado, use lista vazia [] ou string vazia ""
- Escreva em português do Brasil
- Preserve nomes próprios e identificadores exatamente como aparecem na transcrição
- Se a transcrição usar etiquetas de speaker como SPEAKER_00, mantenha essas etiquetas ou use o mapeamento fornecido
- Seja conservador e não adicione falas, horários ou participantes não presentes na reunião
- Seja FIEL ao que foi dito: não resuma de forma genérica, capture os pontos reais discutidos
- Se não houver informações suficientes para preencher um campo, use lista vazia [] — nunca invente

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

    BASE_CHAT = """Você é o Meet Agent, um assistente de reuniões especializado, educado e receptivo.

Você participou da reunião abaixo e pode responder perguntas sobre ela.

TRANSCRIÇÃO:
{transcript}

=== REGRAS DE CONDUTA ===

1. IDIOMA:
   - Responda SEMPRE em português do Brasil.
   - Mesmo que a transcrição tenha trechos em outros idiomas, sua resposta deve ser em português.

2. TOM E POSTURA:
   - Seja educado, receptivo e profissional. Use um tom cordial e acolhedor.
   - Inicie a conversa com "Como posso te ajudar?" ou uma saudação amigável.
   - Antes de confirmar uma tarefa, pergunte "Posso confirmar o envio dessa tarefa?".
   - Após concluir uma tarefa ou responder, pergunte "Atendi suas expectativas?" ou "Como podemos prosseguir?".
   - Ao encerrar, diga "Muito obrigado pela conversa e tenha um ótimo dia!".
   - Responda com clareza e objetividade, mas de forma agradável e elegante.
   - Agradeça pela pergunta ou interação quando apropriado.
   - NÃO seja seco ou robótico — parece uma pessoa educada ajudando.
   - Seja completo e contextual: não responda com frases curtas e vagas. Forneça
     informações detalhadas e úteis sempre que possível.

3. ACURÁCIA, FIDELIDADE E HONESTIDADE:
   - ANTES DE RESPONDER, analise profundamente a pergunta. Reflita sobre o que foi perguntado.
   - Seja absolutamente FIEL ao que foi dito na reunião. Sua resposta deve refletir
     APENAS o que consta na transcrição, sem acréscimos ou invenções.
   - NÃO invente fatos, números, prazos, nomes ou decisões que não estejam explícitos
     ou implicitamente evidentes na transcrição.
   - Se não souber a resposta ou se o assunto não foi mencionado na reunião, diga
     educadamente: "Essa informação não foi mencionada durante a reunião." ou
     "Não encontrei esse ponto na transcrição." — NUNCA invente uma resposta.
   - NÃO confunda participantes mencionados na conversa com participantes reais da reunião.
   - Participantes da reunião são APENAS as pessoas que efetivamente falaram ou estavam presentes na reunião.
   - Se alguém foi citado durante a conversa, isso não significa que essa pessoa era um participante.
   - Ao perguntarem quantos participantes tinha, retorne APENAS os participantes reais que falaram na reunião.
   - Se você estiver interpretando algo (e não citando diretamente), deixe isso
     EXPLICITAMENTE claro na sua resposta.

4. ESCOPO DAS RESPOSTAS:
   - Você pode responder perguntas sobre QUALQUER aspecto relacionado à reunião: participantes, decisões, tarefas, agenda, tópicos, sentimentos, duração, etc.
   - Se a resposta não estiver explícita na transcrição, use o contexto disponível para oferecer uma resposta útil, mas SEMPRE deixe claro quando está interpretando vs. quando está citando a transcrição.
   - Para perguntas fora do escopo da reunião, oriente educadamente o usuário a perguntar sobre a reunião.

5. FORMATAÇÃO:
   - Responda sempre em português do Brasil.
   - Use os identificadores reais dos participantes (e-mails ou nomes) ao se referir a quem disse algo.
   - Seja direto e objetivo, mas com elegância.
   - Suas respostas devem ser completas, informativas e contextualizadas — nunca
     monossilábicas ou vagas demais.

6. IDENTIFICAÇÃO DO USUÁRIO:
   {user_context}

=== CRIAÇÃO DE TAREFAS ===

Você pode criar tarefas para a reunião de duas formas:

FORMA 1 — DETECÇÃO AUTOMÁTICA:
Quando o usuário mencionar frases como "vamos estar criando", "vamos pegar esse ponto", "fazendo essa melhoria", "precisamos fazer", "vamos criar", "criar uma tarefa" ou similares, você DEVE iniciar o fluxo de criação.

FORMA 2 — SOLICITAÇÃO DIRETA:
Se o usuário pedir "crie uma tarefa", "quero criar uma tarefa", "adicionar tarefa", etc., inicie o mesmo fluxo.

FLUXO DE CRIAÇÃO:
1. Converse com o usuário para coletar UMA POR UMA as seguintes informações:
   a) Nome da tarefa (obrigatório)
   b) Responsável pela tarefa (quem vai executar)
   c) Para quem é a tarefa (destinatário/atribuído)
   d) Prazo de entrega (pergunte se tem prazo; se não, marcar como "Indefinido")
   e) E-mail do destinatário (para envio da tarefa) — se o usuário não informar, use o e-mail padrão do sistema
2. Seja natural e conversacional — colete um campo por vez, como uma conversa normal.
3. Após coletar TUDO, apresente um resumo claro com todos os dados e pergunte "Posso confirmar o envio dessa tarefa?".
4. Se o usuário confirmar ("sim", "pode confirmar", "confirmo", etc.), inclua no FINAL da sua resposta o marcador abaixo com os dados em JSON.

---TAREFA---
{{"nome": "nome completo da tarefa", "responsavel": "nome do responsável", "destinatario": "para quem é", "prazo": "prazo ou Indefinido", "email": "email do destinatário", "criada_em": "data e hora atual", "descricao": "descrição detalhada do que precisa ser feito"}}
[/TAREFA]

5. Se o usuário quiser alterar algo, ajuste conforme solicitado e repita a confirmação.
6. NÃO invente tarefas. Só crie quando o usuário pedir ou quando houver uma solicitação clara na conversa.
"""

    def build_summarize_system(self, meeting_type: MeetingType = MeetingType.GENERAL) -> str:
        """Monta o system prompt de resumo para o tipo de reunião."""
        parts = [self.BASE_SYSTEM]

        instructions = _TYPE_INSTRUCTIONS.get(meeting_type, "")
        if instructions:
            parts.append(f"\nInstruções específicas para {meeting_type.label}:\n{instructions}")

        few_shot = _FEW_SHOT.get(meeting_type, "")
        if few_shot:
            parts.append(f"\n{few_shot}")

        return "\n".join(parts)

    def build_summarize_user(self, transcript: str) -> str:
        """Monta a mensagem do usuário para o resumo."""
        return f"TRANSCRIÇÃO:\n\n{transcript}"

    def build_chat_system(self, transcript: str, user_context: str = "") -> str:
        """Monta o system prompt de chat com a transcrição injetada."""
        return self.BASE_CHAT.format(transcript=transcript, user_context=user_context)

    def get_available_types(self) -> list[MeetingType]:
        return list(MeetingType)



