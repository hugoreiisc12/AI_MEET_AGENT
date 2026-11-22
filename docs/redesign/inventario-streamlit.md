# Inventário da interface Streamlit → novo redesign

Fonte: `presentation/streamlit/app.py` (905 linhas). Cada linha abaixo é um componente ou campo
que a interface atual tem. A coluna **Destino** diz onde ele vive no redesign (tela do Pencil em
`design/meet-agent-ui.pen` ou a rota de API que consome).

Legenda do status: **Pencil** = já existe no desenho; **Novo** = não existe no desenho nem na
referência React e precisa ser desenhado; **Ref.** = existe na referência React
(`hugoreiisc12/Interface-AI-Meet`), mas com dados mock.

## 1. Acesso e conta

| Componente | Tipo Streamlit | Campos / ações | Endpoint | Destino | Status |
|---|---|---|---|---|---|
| Título e abas de entrada | `st.title`, `st.tabs` | Abas: Entrar, Criar conta, Esqueci a senha | — | Tela 1/2 (login) | Pencil |
| Login | `st.form("login")` | E-mail, Senha; botão Entrar | `POST /auth/login` | Tela 2 (login recorrente) | Pencil |
| Cadastro | `st.form("signup")` | Nome, E-mail, Senha (mín. `MIN_PASSWORD`), Repita a senha; botão Criar conta. Só aparece se `registration_open` (GET /config) | `POST /auth/register` | Tela de cadastro | **Novo** |
| Esqueci a senha — enviar código | `st.form("forgot")` | E-mail; botão Enviar código (vale 15 min) | `POST /auth/password/forgot` | Tela de recuperação, passo 1 | **Novo** |
| Esqueci a senha — nova senha | `st.form("reset")` | E-mail, Código, Nova senha; botão Criar nova senha | `POST /auth/password/reset` | Tela de recuperação, passo 2 | **Novo** |
| Aviso de recuperação indisponível | `st.info` | Aparece se `email_enabled` é falso | `GET /config` | Estado da tela de recuperação | **Novo** |
| Aviso de cadastro fechado | `st.info` | Aparece se `registration_open` é falso | `GET /config` | Estado da tela de cadastro | **Novo** |
| Sair | `st.button("Sair")` (sidebar) | Encerra a sessão | `POST /auth/logout` | Barra lateral, rodapé | Pencil (ref. "Encerrar sessão") |
| Nome do usuário | `st.caption` (sidebar) | Nome | `GET /auth/me` | Barra lateral, rodapé | Pencil |
| Trocar modo Solo/Colaborativo | `st.button` (sidebar), `st.caption` com o modo | Só admin muda para Solo; mostra o erro de `switch_mode` | (sem endpoint: `switch_mode` local) | Barra lateral, topo | **Novo** |

## 2. Navegação e estrutura

| Componente | Tipo | Campos / ações | Destino | Status |
|---|---|---|---|---|
| Menu de páginas | `st.radio("Navegação")` | Reuniões, Chat Interativo, Minha conta (só colaborativo), Observabilidade (só colaborativo e admin) | Barra lateral (itens de navegação) | Pencil (4 itens; faltam Minha conta e Observabilidade condicionais) |
| Lista "Reuniões salvas" | `st.subheader`, botões por reunião | Ícone de status + título truncado em 30 caracteres; abre a reunião | Barra lateral, lista | **Novo** |
| Atualizar lista | `st.button("🔄 Atualizar")` | Recarrega as reuniões | Barra lateral | **Novo** |
| Fechar reunião | `st.button("✖ Fechar reunião")` | Volta à lista | Cabeçalho da reunião | **Novo** |
| Erro de carregamento | `st.error` | "Erro ao carregar reuniões" | Estado de erro da lista | **Novo** |
| Divisórias | `st.divider` | Separam seções | Espaçamento no desenho | — |

## 3. Reuniões (página principal)

### 3.1 Painel "Em andamento" (fragmento que atualiza a cada 3 s)

| Componente | Campos / ações | Endpoint | Status |
|---|---|---|---|
| Lista de reuniões em andamento | Título, duração decorrida, botão Abrir | `GET /meetings/` (filtrar por status no cliente) | **Novo** |
| Botão Abrir | Abre a reunião | `GET /meetings/{id}` | **Novo** |

### 3.2 Nova reunião por upload (modo solo)

| Campo | Tipo | Regra | Endpoint | Status |
|---|---|---|---|---|
| Título | `st.text_input` | Placeholder "Sprint Planning — Semana 22" | `POST /meetings/upload` | **Novo** |
| Arquivo de áudio | `st.file_uploader` | wav, mp3, m4a, webm, mkv, ogg | `POST /meetings/upload` | **Novo** |
| Identificar speakers | `st.toggle` | Padrão ligado | `POST /meetings/upload` | **Novo** |
| Processar | `st.button` | Desabilitado sem título e arquivo; mostra spinner "Transcrevendo e gerando resumo..." | `POST /meetings/upload` | **Novo** |

### 3.3 Enviar bot para a reunião (modo colaborativo)

| Campo | Regra | Endpoint | Status |
|---|---|---|---|
| Link da reunião | Placeholder `https://meet.google.com/...`; ajuda: Teams e Zoom não validados | `POST /meetings/bot` | **Novo** |
| Título da reunião | Opcional com agenda ligada (vem do evento) | `POST /meetings/bot` | **Novo** |
| Enviar bot | Desabilitado sem credencial do bot (`bot_ready`) | `POST /meetings/bot` | **Novo** |
| Status do bot | `st.info`/`st.warning`/`st.error` e fragmento de progresso a cada 3 s | `GET /bot/status` | **Novo** |
| Credenciar bot | `st.button("🤖 Credenciar bot")`; mostra a tela do navegador do bot quando pede login | `POST /bot/setup` | **Novo** |
| Próximas reuniões da agenda | Lista com botão "🤖 Mandar" por evento; avisos de erro e de lista vazia | `GET /calendar/events` | **Novo** |
| Como funciona | Texto de ajuda fixo | — | **Novo** |

### 3.4 Detalhe da reunião

| Componente | Campos / ações | Endpoint | Status |
|---|---|---|---|
| Título e data | Título, data formatada | `GET /meetings/{id}` | Ref. (título e metadados) |
| Apagar reunião | Botão "Apagar definitivamente" com aviso; bloqueado se estiver em andamento | `DELETE /meetings/{id}` | **Novo** |
| Erro da reunião | `st.error` com a falha; botão "🔁 Reprocessar áudio gravado" | `POST /meetings/{id}/process` | **Novo** |
| Progresso do processamento | `st.info` com etapa e fila; aviso se o worker parou; botão "🔁 Retomar" | `GET /meetings/{id}/status`, `POST /meetings/{id}/resume` | **Novo** |
| Métricas | Duração (min), Participantes, Tarefas, Decisões | `GET /meetings/{id}` | Ref. (parcial) |
| Visão geral | Texto do resumo | `GET /meetings/{id}` | Ref. |
| Tópicos | Lista | idem | Ref. |
| Tarefas | Checkbox por tarefa (marca como feita) | `PATCH /meetings/{id}/tasks/{index}` | Ref. (mock, sem persistência) |
| Enviar tarefas por e-mail | Campo "Enviar tarefas por e-mail para" + botão ✉️; avisos de sucesso e erro | `POST /meetings/{id}/tasks/email` | **Novo** |
| Decisões | Expander por decisão com o contexto | `GET /meetings/{id}` | Ref. |
| Seções extras do resumo | Uma seção por chave de `extra_sections` com emoji e rótulo (ver §7) | `GET /meetings/{id}` | **Novo** |
| Baixar resumo | `st.download_button` `.md` | `GET /meetings/{id}/export.md` | **Novo** |
| Transcrição completa | Expander com texto e botão para baixar `_transcricao.txt` | `GET /meetings/{id}` | **Novo** |

## 4. Chat interativo (página de chat)

| Componente | Campos / ações | Endpoint | Status |
|---|---|---|---|
| Título e subtítulo | "Chat Interativo com IA" e "Agente LangGraph · contrato MEETING-INTELLIGENCE-001" | — | Pencil ("Chat interativo com o agente") |
| Seletor de reunião | `st.selectbox` "Selecione uma reunião para conversar:" | `GET /meetings/` | **Novo** |
| Metadados da reunião | Título em negrito e legenda | — | **Novo** |
| Limpar conversa | Botão "Limpar" (primary) com aviso; apaga conversa, documentos gerados e e-mails não enviados | `DELETE /meetings/{id}/chat` | **Novo** |
| Histórico do chat | Balões usuário/assistente, com rolagem (altura fixa 500) | `GET /meetings/{id}` (campo `chat_history`, confirmado em `api/schemas/meeting.py`) | Pencil (orbe + lista) |
| Entrada de pergunta | `st.chat_input` "Ex: Quais foram as principais decisões?" | `POST /meetings/{id}/chat` | Pencil ("Pergunte sobre a gravação ativa…") |
| Estado "Pensando..." | Spinner | — | **Novo** |
| Ações do agente | Por ação: e-mail (Para, Assunto, Anexos, Corpo em texto), botões Enviar e Descartar; estados "E-mail enviado" e "E-mail descartado" | `POST /meetings/{id}/actions/{action_id}/send` e `/cancel` | **Novo** |
| Documento gerado | Botão "📄 Baixar {arquivo}" ou aviso "não está mais disponível" | `GET /meetings/{id}/actions/{action_id}/document` | **Novo** |
| Memória salva | Aviso "🧠 Guardado na sua memória" | — | **Novo** |

## 5. Minha conta (só colaborativo)

| Componente | Campos / ações | Endpoint | Status |
|---|---|---|---|
| Cabeçalho | Nome, e-mail, marca "administrador" | `GET /auth/me` | Pencil (tela 6 "Configurações", parcial) |
| Memória do agente | Lista de notas com botão Apagar por nota | `GET /memory/`, `DELETE /memory/{note_id}` | **Novo** |
| Sessões abertas | Lista com botão Encerrar por sessão (exceto a atual); checkbox "Confirmo: encerrar as outras N sessões"; botão Encerrar todas as outras | `GET /auth/sessions`, `DELETE /auth/sessions/{sid}`, `DELETE /auth/sessions` | **Novo** |
| Trocar senha | Senha atual, Nova senha (mín.), Repita a nova senha; botão Trocar senha; limpa o formulário ao enviar | `POST /auth/password` | **Novo** |
| Administração: limpar sessões (admin) | Radio "O que limpar" (escopo), seletor de usuário quando for por usuário, campo "Digite LIMPAR para confirmar", botão Limpar sessões | `DELETE /auth/sessions` com escopo | **Novo** |

## 6. Observabilidade (só colaborativo e admin)

| Componente | Campos / ações | Endpoint | Status |
|---|---|---|---|
| Estado dos serviços | 5 métricas: Transcrição, Resumo (LLM), Bot, LLM (modelo), Disco livre | `GET /observability/summary` | **Novo** |
| Totais | Reuniões (com erros), Usuários, Pedidos à API (5xx), E-mails | `GET /observability/summary` | **Novo** |
| Tempos (amostras) | Tabela `st.dataframe` | `GET /observability/summary` | **Novo** |
| Logs | Filtros: Reunião (id), Serviço (select), Nível mínimo (select), Texto; tabela de resultados | `GET /observability/logs` | **Novo** |
| Atualizar | Botão | — | **Novo** |
| Métricas Prometheus | — (só via API, não há tela) | `GET /observability/metrics` | — |

## 7. Seções extras do resumo (chaves de `extra_sections`)

Mapeamento de rótulo e emoji. Vale para o detalhe da reunião e precisa aparecer no redesign:

| Chave | Rótulo | Emoji |
|---|---|---|
| `went_well` | Pontos Fortes / o que deu certo | ✅ |
| `to_improve` | a melhorar | 🔧 |
| `action_items` | Ações | 📌 |
| `risks` | Riscos | ⚠️ |
| `delivered` | Entregue | 📦 |
| `not_delivered` | Não entregue | ⏳ |
| `stakeholder_feedback` | Feedback | 💬 |
| `feedbacks` | Feedbacks | 🔄 |
| `strengths` | Pontos Fortes | 💪 |
| `concerns` | Pontos de Atenção | 🚩 |
| `recommendation` | Recomendação | 🎯 |
| `ideas` | Ideias | 💡 |

Chaves fora da tabela aparecem com o nome da chave em título.

## 8. Lacunas do redesign atual (Pencil e referência React)

A referência React (`Interface-AI-Meet`) e o `.pen` cobrem: login (2 telas), Estúdio ao vivo,
Gravações, Regras e Configurações. Essas telas **não correspondem** às funções reais:

- A referência usa dados mock em `localStorage` e chama `/api/agent/analyze` e `/api/agent/chat`,
  que **não existem** na API FastAPI. O Estúdio ao vivo (captura pelo microfone, fala simulada) não
  tem equivalente na API atual: a captura real é feita pelo bot, e o upload é o caminho do modo solo.
- Não há telas para: cadastro, recuperação de senha, reuniões e seu detalhe, envio do bot, agenda,
  chat por reunião com ações de e-mail e documentos, memória, sessões, troca de senha e
  observabilidade.
- "Regras do Agente" (gatilhos e VAD) não existe no Streamlit nem na API. Ou é removido do escopo,
  ou precisa de endpoint novo. Decisão pendente.

## 9. Próximos passos

1. Decidir o alvo da refatoração (ver pergunta na resposta).
2. Desenhar as telas **Novo** no `.pen` (cadastro, recuperação, lista e detalhe de reunião, upload,
   envio do bot, agenda, chat com ações, memória, sessões, senha, observabilidade).
3. Implementar consumindo a API FastAPI (`docs/api/openapi.json`), com os mesmos fluxos de §1 a §6.
