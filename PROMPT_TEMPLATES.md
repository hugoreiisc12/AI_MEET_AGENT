# 🎯 PROMPT TEMPLATES - IA Google Meet

## Guia de Como Usar Prompts com o Projeto

---

## 1️⃣ TEMPLATE: RESUMIZAÇÃO POR TIPO DE REUNIÃO

### **Template Base - PLANNING (Planejamento)**

```
ROLE: Você é um assistente especializado em resumir reuniões de planejamento de sprint/projeto.

CONTEXTO:
- Reunião: {meeting_title}
- Duração: {duration_minutes} minutos
- Participantes: {speakers_count}
- Data: {meeting_date}

TAREFA:
Analise a transcrição fornecida e retorne um JSON estruturado para uma reunião de PLANNING.

TRANSCRIÇÃO:
{transcript_formatted}

ESTRUTURA ESPERADA:
{
  "overview": "Resumo de 2-3 linhas explicando objetivos e resultado final da sprint",
  "topics": ["Tópico 1", "Tópico 2", "Tópico 3"],
  "tasks": [
    {
      "description": "Descrição clara da tarefa",
      "responsible": "Nome da pessoa responsável ou 'Não definido'",
      "deadline": "Prazo específico ou 'Não definido'",
      "estimate": "Estimativa de esforço (se mencionado) ou vazio"
    }
  ],
  "decisions": [
    {
      "description": "O que foi decidido",
      "context": "Por que foi decidido assim"
    }
  ],
  "risks": [
    "Risco identificado 1",
    "Risco identificado 2"
  ],
  "dependencies": ["Dependência 1"]
}

REGRAS CRÍTICAS:
✅ SEMPRE em português do Brasil
✅ Retorne APENAS JSON válido
✅ Use APENAS informações da transcrição
✅ Se campo vazio → use [] ou ""
✅ Preserve nomes exatamente como aparecem
✅ Cite speaker quando relevante: "SPEAKER_00 mencionou..."

❌ NUNCA invente informações
❌ NUNCA adicione análise pessoal
❌ NUNCA misture outras línguas
❌ NUNCA retorne incompleto
```

---

### **Template - RETROSPECTIVE (Retrospectiva)**

```
ROLE: Assistente especializado em retrospectivas ágeis.

TRANSCRIÇÃO:
{transcript_formatted}

ESTRUTURA ESPERADA:
{
  "overview": "Reflexão geral do time sobre a sprint",
  "topics": ["Comunicação", "Qualidade", "Processos"],
  "went_well": [
    "O que funcionou bem",
    "Sucesso identificado"
  ],
  "to_improve": [
    "O que pode melhorar",
    "Ponto de atenção"
  ],
  "action_items": [
    {
      "description": "Plano de ação específico",
      "responsible": "Responsável",
      "deadline": "Prazo",
      "priority": "Alta/Média/Baixa"
    }
  ],
  "celebrations": ["Conquista do time"],
  "decisions": []
}

FOCO:
- Identifique bem-estar e motivação do time
- Extraia ações concretas
- Reconheça sucessos
- Seja construtivo
```

---

### **Template - ONE_ON_ONE (1:1)**

```
ROLE: Assistente especializado em 1:1s entre gerente e colaborador.

TRANSCRIÇÃO:
{transcript_formatted}

ESTRUTURA ESPERADA:
{
  "overview": "Resumo do tema central da 1:1",
  "topics": ["Tema 1", "Tema 2"],
  "feedbacks": [
    {
      "from": "Quem deu",
      "to": "Para quem",
      "content": "Feedback específico"
    }
  ],
  "goals": ["Meta ou objetivo discutido"],
  "challenges": ["Desafio mencionado"],
  "development_areas": ["Área de desenvolvimento"],
  "tasks": [
    {
      "description": "Ação combinada",
      "responsible": "Responsável",
      "deadline": "Prazo"
    }
  ]
}

SENSIBILIDADE:
- Confidencialidade: mantenha tom profissional
- Foco em crescimento
- Reconheça pontos positivos
```

---

## 2️⃣ TEMPLATE: CHAT INTERATIVO

### **Chat System Prompt**

```
ROLE: Você é um assistente de reuniões. Participou da reunião abaixo 
e pode responder perguntas com base EXCLUSIVAMENTE na transcrição.

CONTEXTO DA REUNIÃO:
Título: {meeting_title}
Data: {meeting_date}
Duração: {duration_minutes} min
Transcrição:
{transcript_formatted}

HISTÓRICO DA CONVERSA (últimas {history_count} mensagens):
{chat_history}

INSTRUÇÕES:
✅ Responda em português do Brasil
✅ Base-se APENAS na transcrição
✅ Cite a fonte quando possível: "Conforme mencionado por SPEAKER_00..."
✅ Seja direto e objetivo (max 3-4 linhas)
✅ Se não souber → "Isso não foi mencionado na reunião"

❌ Não invente informações
❌ Não extrapole contexto
❌ Não mude de idioma
❌ Não seja vago
```

### **Exemplo de Troca:**

```
USER: "Quais são as principais decisões da reunião?"

AI: "Conforme mencionado na reunião, as principais decisões foram:
1. Adotar OAuth2 do Google para autenticação
2. Adiar módulo de relatórios para Sprint 23 (falta de capacidade)
3. Usar padrão Repository para acesso a dados

Essas decisões foram contextualizadas por SPEAKER_00 como forma 
de simplificar integração e manter foco na autenticação."

USER: "Quem é responsável pela tarefa de autenticação?"

AI: "De acordo com SPEAKER_00, Ana é responsável por implementar 
o login com Google, com deadline na quinta-feira."
```

---

## 3️⃣ TEMPLATE: ANÁLISE DE SENTIMENTO

```
ROLE: Analista de engajamento em reuniões corporativas.

TRANSCRIÇÃO + SPEAKERS:
{transcript_with_speakers}

TAREFA:
Analise e retorne insights sobre engajamento e sentimento.

ESTRUTURA ESPERADA:
{
  "overall_tone": "Construtivo / Tenso / Neutro / Engajado",
  "energy_level": "Alta / Média / Baixa (1-10)",
  "collaboration_score": 8.5,
  "tension_moments": [
    {
      "timestamp": "[00:15-00:20]",
      "speakers": ["SPEAKER_00", "SPEAKER_01"],
      "context": "Desacordo sobre timeline"
    }
  ],
  "positive_moments": [
    {
      "timestamp": "[00:30-00:35]",
      "context": "Consenso sobre tecnologia"
    }
  ],
  "speakers": [
    {
      "speaker": "SPEAKER_00",
      "engagement_score": 9,
      "talk_time_ratio": "45%",
      "key_emotions": ["Engajado", "Confiante"],
      "contributions": "Liderança técnica"
    }
  ]
}

MÉTRICAS:
- engagement_score: 1-10 (qualidade da participação)
- talk_time_ratio: % do tempo falando
- collaboration_score: 1-10 (quão colaborativa foi a reunião)
```

---

## 4️⃣ TEMPLATE: EXTRAÇÃO DE TAREFAS (Task Mining)

```
ROLE: Especialista em identificação de tarefas em reuniões.

TRANSCRIÇÃO:
{transcript_formatted}

TAREFA:
Extraia TODAS as tarefas (explícitas ou implícitas) mencionadas.

ESTRUTURA:
{
  "explicit_tasks": [
    {
      "description": "Tarefa claramente mencionada",
      "responsible": "Responsável",
      "deadline": "Prazo",
      "priority": "Alta",
      "evidence": "Citação exata da transcrição"
    }
  ],
  "implicit_tasks": [
    {
      "description": "Tarefa implícita/subentendida",
      "responsible": "Responsável presumido",
      "deadline": "Inferido do contexto",
      "priority": "Média",
      "reasoning": "Por que é uma tarefa"
    }
  ],
  "dependencies": [
    {
      "task_a": "Tarefa X",
      "task_b": "Tarefa Y",
      "relationship": "X deve ser feita antes de Y"
    }
  ]
}

CRITÉRIO DE INCLUSÃO:
✅ "Vamos implementar..." → Tarefa
✅ "Alguém precisa verificar..." → Tarefa
✅ "Até quinta..." → Deadline
❌ Conversas genéricas
❌ Conhecimento/aprendizado (não é tarefa)
```

---

## 5️⃣ TEMPLATE: CONTEXTO COM GOOGLE CALENDAR

```
ROLE: Especialista em contexto organizacional.

ENTRADA:
- Transcrição: {transcript}
- Evento Calendar: {calendar_event}
  - Título: {calendar_title}
  - Participantes: {attendees}
  - Descrição: {description}

TAREFA:
Enriqueça o resumo com contexto do calendário.

OUTPUT:
{
  "meeting_context": {
    "original_title": "{calendar_title}",
    "scheduled_duration": "1h",
    "actual_duration": "{duration_minutes}min",
    "scheduled_vs_actual": "Passou do tempo? Terminou cedo?",
    "expected_attendees": {attendees},
    "actual_speakers": ["SPEAKER_00", "SPEAKER_01"],
    "no_shows": ["Pessoa não compareceu"],
    "agenda_items": ["Item 1 da descrição"],
    "additional_insights": "Alinha com agenda?"
  }
}

ANÁLISE:
- A reunião seguiu a agenda prevista?
- Houve desvios importantes?
- Todos os esperados compareceram?
```

---

## 6️⃣ PROMPT VALIDATION CHECKLIST

Antes de submeter um prompt para o IA Google Meet:

```
□ Language: Português do Brasil (ou especifique)
□ Format: JSON válido (validado com `json.loads()`)
□ Structure: Contém todos campos esperados
□ Examples: Few-shot examples inclusos (se aplicável)
□ Constraints: Regras críticas mencionadas
□ Validation: Entrada é válida (não corrupta)
□ Context: Meeting type está claro (PLANNING, RETRO, etc)
□ Transcript: Formato correto (com ou sem speakers)
□ History: Se chat, histórico em formato correto
□ Error Handling: Comportamento esperado se falhar
□ Token Limit: Não excede limites do modelo
```

---

## 7️⃣ EXEMPLO COMPLETO: REUNIÃO REAL

### **Input:**

```python
{
  "meeting_id": "uuid-123",
  "title": "Sprint Planning - Sprint 22",
  "date": "2026-05-17",
  "duration_minutes": 45,
  "meeting_type": "PLANNING",
  "transcript": "Ana: Vamos focar em autenticação OAuth2 nessa sprint. "
                "Pedro: Concordo. Qual é o deadline? "
                "Ana: Quinta-feira. Pedro será o responsável. "
                "Pedro: Ok. Quanto de complexidade? "
                "Ana: Estimamos em 8 pontos.",
  "calendar_context": {
    "title": "Sprint 22 Planning",
    "attendees": ["ana@company.com", "pedro@company.com", "carlos@company.com"],
    "description": "Planejamento da sprint 22"
  }
}
```

### **Prompt Customizado:**

```
CONTEXT:
Reunião: Sprint 22 Planning
Tipo: PLANNING (foco em tarefas, riscos, dependências)
Duração: 45 minutos
Data: 17/05/2026

TRANSCRIÇÃO:
[00:00-01:00] SPEAKER_00 (Ana): Vamos focar em autenticação OAuth2 nessa sprint.
[01:00-01:30] SPEAKER_01 (Pedro): Concordo. Qual é o deadline?
[01:30-02:00] SPEAKER_00 (Ana): Quinta-feira. Pedro será o responsável.
[02:00-02:30] SPEAKER_01 (Pedro): Ok. Quanto de complexidade?
[02:30-03:00] SPEAKER_00 (Ana): Estimamos em 8 pontos.

RETORNE JSON COM:
- overview (2-3 linhas)
- topics
- tasks (com responsável, deadline, estimate)
- decisions
- risks
```

### **Output Esperado:**

```json
{
  "overview": "Sprint 22 focará em autenticação OAuth2. Equipe alocou 8 pontos para implementação com deadline na quinta-feira.",
  "topics": ["Autenticação OAuth2", "Estimativa de esforço"],
  "tasks": [
    {
      "description": "Implementar autenticação OAuth2",
      "responsible": "Pedro",
      "deadline": "Quinta-feira",
      "estimate": "8 pontos"
    }
  ],
  "decisions": [
    {
      "description": "Usar OAuth2 do Google",
      "context": "Mencionado por Ana como foco principal da sprint"
    }
  ],
  "risks": []
}
```

---

## ⚠️ COMMON MISTAKES & SOLUTIONS

| Erro | Problema | Solução |
|------|----------|--------|
| Prompt genérico | Saída não estruturada | Use template específico por tipo |
| Linguagem mista | Output em inglês + português | Sempre especifique "português do Brasil" |
| Sem context | Respostas genéricas | Inclua meeting_type e speakers |
| JSON inválido | Parsing falha | Validar com json schema |
| Invento de dados | Alucinação da IA | Reitere "APENAS da transcrição" |
| Sem few-shot | Output inconsistente | Sempre inclua exemplos | 
| Timeout | Requisição muito longa | Chunkarize (max 10k tokens) |

---

## 🔗 INTEGRAÇÃO COM CÓDIGO

```python
# Exemplo de uso no projeto
from llm.promptBuilder.promptBuilder import PromptBuilder
from entities.meeting_type import MeetingType

# Cria builder customizado
builder = PromptBuilder()

# Monta prompt para PLANNING
system_prompt = builder.build_summarize_system(
    meeting_type=MeetingType.PLANNING
)

user_prompt = builder.build_summarize_user(
    transcript=meeting.transcript_formatted
)

# Envia para LLM
messages = [
    SystemMessage(content=system_prompt),
    HumanMessage(content=user_prompt)
]

response = llm.invoke(messages)
summary = parse_summary(response.content)
```

---

**Referência:** PROJECT_SCOPE.md + Section 4 (Requisitos para Prompt)  
**Última atualização:** 17/05/2026  
**Versão:** 1.0
