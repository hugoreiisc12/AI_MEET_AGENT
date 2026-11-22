# Roteiro para produção — Meet Agent

Ordem por prioridade: primeiro o que impede o fluxo de funcionar, depois o que impede de
manter, depois o que impede de expor, e só então evolução. Cada sprint tem um critério de saída
verificável; não se inicia a seguinte sem ele.

Decisões de arquitetura: [docs/adr/README.md](adr/README.md).
Convenção de id: `S<sprint>-<n>`. Tipo: `fix`, `feat`, `refactor`, `chore`.

## Sprint 0 — Linha de base (1 a 2 dias)

**Concluída em 2026-11-14.** Bot gravou uma reunião real de 10 min.

Objetivo: estado atual versionado, testes verdes, bot gravando.

| Id | Tipo | Tarefa | Pronto quando |
|----|------|--------|---------------|
| S0-1 | chore | Ignorar `data/` inteiro, `security_config.json`, `security_audits/`, `htmlcov/`, `.qodo/`; criar branch e commitar a árvore atual | `git status` limpo; nenhum arquivo de `data/` rastreado |
| S0-2 | fix | `chrome.runstime` → `chrome.runtime` em `extension/background.js:16` | Uma reunião real gera `data/audio/<id>.webm` com tamanho > 0 |
| S0-3 | fix | Remover `test/test_audio_capture_local.py` (testa arquivo apagado) | `pytest` coleta sem erro |
| S0-4 | fix | `LangChainLLMService.summarize` usar o cliente injetado; provedor decidido no construtor | Os 3 testes de `test_prompt_builder.py` passam sem Ollama no ar |
| S0-5 | fix | Renomear `dockerfile.streamlit` → `Dockerfile.streamlit`; corrigir `requirements_diarization.txt` | `docker compose build` passa |
| S0-6 | fix | Status `fallback_legendas` fora do enum; `MONGO_DB_NAME` vs `MONGO_DB` | `GET /meetings/{id}/status` não devolve 500; nome do banco vem do `.env` |

Saída: `pytest` verde com o gate de cobertura atual, e um `.webm` real gravado pelo bot.

## Sprint 1 — Consolidação (ADR-001 a 005)

**Concluída em 2026-11-14.** Desvios registrados em [adr/README.md](adr/README.md). S1-8 não foi necessária.

Objetivo: um caminho de execução, um schema, uma fonte de status. É a sprint que mais apaga código.

| Id | Tipo | Tarefa | Pronto quando |
|----|------|--------|---------------|
| S1-1 | refactor | Enum de status e campos `status`/`error` na entidade `Meeting`; `update_status` no contrato do repositório | Teste de repositório cobre gravação e leitura de status nos dois backends |
| S1-2 | refactor | Repositório Mongo síncrono com PyMongo e schema único; JSON persistindo os mesmos campos | Ida e volta de um `Meeting` completo sem perda de campo; Beanie e Motor fora dos requirements |
| S1-3 | feat | `ProcessMeetingUC` com status por etapa, erro persistido e idempotência por id | Teste: falha de transcrição deixa `status=error` com mensagem; reprocessar o mesmo id não duplica |
| S1-4 | refactor | Celery, upload da API e Streamlit chamando só `ProcessMeetingUC` | Nenhuma outra sequência transcrever→resumir no código |
| S1-5 | refactor | Remover orquestradores, agentes, repositórios e storages órfãos (lista na ADR-001 e ADR-009 fase 1), `_FallbackTask`, scripts quebrados | Busca pelos nomes removidos não retorna nada; testes verdes |
| S1-6 | refactor | Portas num só lugar (`domain/interfaces/`); remover `interface/` e `repositories/` | Imports atualizados; testes verdes |
| S1-7 | refactor | Settings como única leitura de ambiente, validação na partida em collab, `.env.example` | Subir collab sem `MONGO_URI` falha com mensagem clara |
| S1-8 | chore | Script de migração dos documentos existentes para o schema novo | Reuniões antigas aparecem na UI com status correto |

Saída: upload manual funciona em solo e em collab pelo mesmo caso de uso, e uma falha forçada
aparece como erro na UI.

## Sprint 2 — Bot em produção (ADR-006)

**Implementada em 2026-11-14; falta o critério de saída** (três reuniões reais pelo fluxo da fila).
Validado: compose completo no ar, upload real processado no container até `done`, fila `bot`
entregando ao worker do host e falha persistida. S2-6 feita em 2026-11-15:
`python -m infrastructure.recorder.run_bot --url <link> --smoke 30` entra, grava 30 s, confere
áudio, legendas, presentes e bloco do bot, apaga o que criou e sai com código 1 se algo faltou.

Como subir:

    docker compose up -d --build        # api :8001, streamlit :8501, redis :6380, mongo :27018
    python main.py --bot-worker         # no host, em outro terminal

Objetivo: URL do Meet entra, reunião resumida sai, sem intervenção e sem bloquear nada.

| Id | Tipo | Tarefa | Pronto quando |
|----|------|--------|---------------|
| S2-1 | feat | Task `join_meeting` na fila `bot`; `meeting_id` criado no despacho e usado como sessão de captura | `POST /meetings/bot` responde em menos de 1 s com o id |
| S2-2 | refactor | Recorder recebe o id e o endpoint de captura por parâmetro; grava `started_at` real; atualiza status | Documento passa por `recording` → `transcribing` → `summarizing` → `done` |
| S2-3 | feat | Worker do bot na fila `bot`, concorrência 1. **No host por enquanto** (ver ADR-006); container fica para quando houver servidor | Bot grava uma reunião despachada pela fila |
| S2-4 | refactor | Streamlit despacha pela fila e mostra status do documento; remover subprocesso e leitura de `bot_session_*.json` | UI mostra o andamento sem Refresh manual do processo |
| S2-5 | fix | Encerramento: áudio parcial é processado quando o bot cai ou recebe SIGTERM | Matar o container no meio da reunião ainda gera resumo do que foi gravado |
| S2-6 | feat | Teste de fumaça do bot contra uma reunião de teste, executável sob demanda | Um comando valida entrar, gravar 30 s e sair |

Saída: três reuniões reais seguidas processadas de ponta a ponta no ambiente de compose.

## Sprint 2B — Quem estava e quem falou o quê (ADR-009 fase 2)

Antecipada da Sprint 4 em 2026-11-14: hoje o chat responde "Speaker 0 / Speaker 1" e o produto
precisa do nome de cada participante. Vem antes do endurecimento porque a implantação atual é
local; a Sprint 3 continua obrigatória antes de expor a API fora da máquina.

Objetivo: a reunião guarda quem esteve presente e a transcrição atribui cada fala ao nome real.

| Id | Tipo | Tarefa | Pronto quando |
|----|------|--------|---------------|
| S2B-1 | chore | Diagnóstico do DOM do Meet: com `BOT_DEBUG_DOM=true` o bot salva amostras dos blocos de participantes e de legendas durante uma reunião real | Arquivo `data/audio/<id>.dom.jsonl` de uma reunião com 2+ pessoas; seletores escolhidos a partir dele |
| S2B-2 | feat | Extensão: observar legendas (nome de quem fala + instante) e a lista de participantes, e enviar para a API | Eventos chegam em `data/audio/<id>.speakers.jsonl` durante a reunião |
| S2B-3 | feat | API: `POST /capture/speakers` grava os eventos da sessão | Teste cobre gravação e sessão inválida |
| S2B-4 | feat | Alinhamento: atribuir a cada segmento do Whisper o nome com maior sobreposição de tempo, tolerando o atraso das legendas; sem evidência, mantém "Speaker N" | Função pura com testes: sobreposição, atraso, troca rápida de falante, ausência de eventos |
| S2B-5 | feat | `ProcessMeetingUC` aplica o alinhamento; `participants` passa a ser a lista de nomes reais (sem o bot) | Reunião real: transcrição com nomes; campo `participants` com os presentes |
| S2B-6 | feat | Chat e resumo recebem a lista de participantes no prompt | Pergunta "quem estava na reunião?" devolve os nomes; tarefas saem com responsável pelo nome |
| S2B-7 | chore | Teste de fumaça dos seletores, executável sob demanda (entra com o S2-6) | Um comando acusa quando o Meet mudou a tela |

Saída: reunião real com 3 pessoas em que o chat lista os 3 nomes e a transcrição atribui as falas corretamente.

**Estado em 2026-11-15:** S2B-1 a S2B-6 implementadas e validadas numa reunião real com a conta
do dono como anfitriã: o bot esperou a admissão, ligou as legendas, registrou o anfitrião como
presente e retirou o próprio nome. Detalhes na ADR-009.
- A leitura das legendas ficou no recorder, não na extensão; `POST /capture/speakers` não existe.
- S2B-7 é o mesmo comando da S2-6 (`run_bot --smoke`); passou numa reunião real em 2026-11-15.
- Nome de terceiros com duas ou mais pessoas falando: validado pelo dono do produto em 2026-11-15.

Limites conhecidos, para não prometer o que o Meet não entrega:
- O bot enxerga o **nome de exibição** de cada participante, não o e-mail nem um id estável da conta.
- Quem entrou e nunca falou aparece em `participants`, mas não na transcrição.
- A atribuição depende das legendas do Meet estarem ligadas (o bot liga) e do Meet reconhecer a fala;
  trechos sem legenda ficam como "Speaker N".
- Os seletores do Meet mudam sem aviso; por isso o S2B-7.

## Sprint 3 — Endurecimento (ADR-007, ADR-008)

**Implementada em 2026-11-15.** Pendências: recriar o venv local em 3.11 (S3-4), ver o CI rodar no
GitHub depois do push (S3-6) e o critério de saída (implantar num servidor limpo). S3-3 já estava
feita desde a Sprint 1. Os `print` que restam são saída de linha de comando (`main.py --test`,
`bot_setup`, `run_bot`).

Objetivo: seguro para expor e reproduzível para implantar.

| Id | Tipo | Tarefa | Pronto quando |
|----|------|--------|---------------|
| S3-1 | feat | Chave de API em todas as rotas; token por sessão em `/capture/*` | Chamada sem credencial devolve 401; teste cobre |
| S3-2 | fix | Upload em streaming com teto; limite por chunk e por sessão de captura | Arquivo acima do teto devolve 413 sem encher memória |
| S3-3 | fix | Remover `/meetings/bot/done` e qualquer caminho de arquivo vindo do cliente | Nenhum schema de entrada tem campo de caminho |
| S3-4 | chore | Python 3.11, `pip-compile`, requirements separados, imagem única para api/worker/streamlit | Build reproduzível; venv local recriado em 3.11 com testes verdes |
| S3-5 | feat | Logging padrão com `meeting_id` em toda linha; remover `print`; `/health` checando Mongo e Redis | Dá para seguir uma reunião pelos logs só com o id |
| S3-6 | chore | CI: testes e build de imagens a cada push | Push com teste quebrado falha no CI |
| S3-7 | chore | Backup do volume do Mongo e política de retenção dos `.webm` | Restauração testada uma vez; áudio antigo é apagado por regra |
| S3-8 | chore | Reescrever o README para o que existe | Alguém sobe o ambiente seguindo só o README |

Saída: implantação em um servidor limpo a partir do repositório, com API fechada por chave.

## Sprint 4 — Qualidade e escala (ADR-009, ADR-010)

**Implementada em 2026-11-15.** Medições e decisão na ADR-010. S4-5: exportação Markdown sempre
ligada, e-mail de tarefas com `SMTP_USER`/`SMTP_PASSWORD`, agenda com `ENABLE_CALENDAR` (dá o
título da reunião). E-mail e agenda foram testados com serviços simulados, não com SMTP nem com a
API do Google de verdade.

Objetivo: melhorar o resultado, com medição antes de cada mudança.

| Id | Tipo | Tarefa | Pronto quando |
|----|------|--------|---------------|
| S4-1 | chore | Medir tokens por reunião, tempo de transcrição e taxa de falha por provedor | Números registrados na ADR-010 |
| S4-2 | feat | Estratégia de contexto escolhida na ADR-010 | Reunião de 2 h resume e responde no chat sem erro de contexto |
| S4-3 | — | Movida para a Sprint 2B a pedido do dono do produto | — |
| S4-4 | feat | Persistir conclusão de tarefas e histórico de chat | Marcar tarefa sobrevive a recarregar a página |
| S4-5 | feat | Reativar o que já existe e está desligado, um por vez: e-mail de tarefas, exportação Markdown, Google Calendar | Cada um com teste e chave de configuração própria |

## Sprint 5 — Usuários, plataformas e contrato da API (ADR-011, 012, 013)

**Implementada em 2026-11-15**, com as ressalvas de S5-5 e S5-6.

Objetivo: cada pessoa com a própria conta e as próprias reuniões; bot além do Meet; API pronta
para um front novo.

| Id | Tipo | Tarefa | Estado |
|----|------|--------|--------|
| S5-1 | feat | Cadastro e login; senha com scrypt; sessões na coleção `sessions` do MongoDB com validade e TTL | Feito; testado contra o Mongo do compose |
| S5-2 | feat | `owner_id` na reunião; cada usuário vê só as suas; a primeira conta herda as antigas | Feito; teste cobre todas as rotas |
| S5-3 | feat | Tela de entrar e criar conta no Streamlit; botão Sair | Feito; falta o dono criar a primeira conta |
| S5-4 | feat | Camada de plataformas no bot; link validado no despacho | Feito; Meet revalidado em reunião real |
| S5-5 | feat | Teams e Zoom pelo cliente web, como convidado | **Escrito, não validado**: precisa de uma reunião real de cada |
| S5-6 | feat | Discord | **Adiado** (ADR-012): exige bot oficial com token, não navegador |
| S5-7 | chore | OpenAPI completo em `/docs` e `docs/api/openapi.json`; rotas que faltavam para um front | Feito |

Saída: duas contas, cada uma enviando o bot a uma reunião e vendo só a própria. **Pendente** (depende de pessoas).

## Caminho até a versão 1.0 em produção

Planejado em 2026-11-15 a pedido do dono do produto; ADR-015, ADR-016 e Discord depois da 1.0
aceitos pelo dono no mesmo dia. Ordem: primeiro o que mexe em segurança e
dados de usuário (7), depois o agente (8), depois a capacidade para N usuários (9), que define a
topologia final dos containers; só então Windows (10), que depende dessa topologia, e a
implantação (11). A Sprint 6 depende de contas de Zoom/Teams e de credenciais reais e pode
correr em paralelo às demais.

```
S6 validação real ──────────────────────────────┐
S7 contas/sessões ─► S8 LangGraph ─► S9 fila/N usuários ─► S10 Windows ─► S11 v1.0 em produção
```

## Sprint 6 — Validação com serviços reais

| Id | Tipo | Tarefa | Pronto quando |
|----|------|--------|---------------|
| S6-1 | chore | Teste de fumaça do bot no Zoom e no Teams, corrigindo seletores a partir do `.dom.jsonl` | `run_bot --smoke` verde nas duas |
| S6-2 | feat | Nome de quem fala no Teams e no Zoom (legendas de cada um) | Transcrição com nomes fora do Meet |
| S6-3 | chore | E-mail de tarefas com SMTP real | **Enviado em 2026-11-15** (tarefas e chat confirmado) para a caixa de teste do dono; falta ele confirmar o recebimento |
| S6-4 | chore | Google Calendar com a API real | **Código pronto em 2026-11-15** (login no host, links de Meet/Zoom/Teams, lista com "Mandar"); falta o `credentials.json` do dono |
| S6-5 | — | Movida para a Sprint 7 (S7-5), junto do resto das contas | — |
| S6-6 | — | Discord: movido para depois da 1.0 (é outra arquitetura de captura e não bloqueia nada) | — |
| S6-7 | chore | venv local em Python 3.11; CI verde no GitHub | Feito em 2026-11-15: `.venv` (3.11, versões travadas) com testes verdes e o OpenAPI idêntico ao do container. Falta trocar o worker do bot para ele (Playwright 1.65 baixa outro Chromium; ver CHANGELOG) |

## Sprint 7 — Contas, sessões e isolamento por perfil (ADR-011)

**Implementada em 2026-11-15.** Tudo coberto por testes e validado no navegador, menos o e-mail de
recuperação com SMTP real (S7-5), que não foi disparado. Detalhes em "Ampliação da Sprint 7", na ADR-011.

Objetivo: cada usuário controla as próprias sessões, e reuniões de perfis diferentes nunca se
misturam, nem quando dois usuários usam o mesmo link ao mesmo tempo.

Estado conferido em 2026-11-15: reuniões já têm dono (`owner_id`) e cada usuário só vê as suas.
Faltam índice no banco, regra para links repetidos e o controle de sessões. No Streamlit cada F5
pede login e abre uma sessão nova, que fica no banco até vencer: é a origem do acúmulo.

| Id | Tipo | Tarefa | Pronto quando |
|----|------|--------|---------------|
| S7-1 | fix | Streamlit mantém a sessão ao atualizar a página (token em cookie, validado no banco) | F5 não pede login nem cria sessão nova |
| S7-2 | feat | "Minhas sessões": lista as sessões ativas do usuário (aparelho, IP, data) com **Encerrar** e **Encerrar todas as outras**; rotas `GET/DELETE /auth/sessions` | Só afeta sessões do próprio usuário; pede confirmação; a sessão atual continua; nunca mostra o token |
| S7-3 | feat | Papel `admin` (a primeira conta) com botão **Limpar sessões**: vencidas, de um usuário, ou todas menos a sua | Exige digitar a confirmação; grava quem limpou e quantas, no log; nunca apaga usuários nem reuniões |
| S7-4 | feat | Isolamento por perfil: índice `owner_id + started_at`; o mesmo usuário não envia o bot duas vezes ao mesmo link em andamento (409); dois usuários no mesmo link recebem cada um a sua reunião, com chat e tarefas próprios | Teste com dois usuários simultâneos no mesmo link: duas reuniões, nenhum dado cruzado |
| S7-5 | feat | (era S6-5) Recuperação de senha por e-mail, troca de senha e limite de tentativas de login | Cinco senhas erradas bloqueiam por alguns minutos; link de recuperação expira |

Saída: dois usuários, cada um em seu navegador, com sessões e reuniões independentes; o admin
limpa as sessões vencidas sem afetar ninguém logado.

## Sprint 8 — Agente com LangGraph e contrato (ADR-014)

**Implementada em 2026-11-15.** Avaliação de 3/8 (antes) para 8/8 (depois), em duas rodadas; números na ADR-014.
O contrato ficou em `SPEC_CONTRACT.md`, na raiz, onde o dono o colocou (não em `docs/agent/`).
Memória entre reuniões (§14) entregue em 2026-11-15: ADR-020.

Objetivo: o chat e o resumo viram um grafo explícito (LangGraph) que aplica o contrato do agente
em cada resposta, sem perder o que a ADR-010 resolveu para reuniões longas.

| Id | Tipo | Tarefa | Pronto quando |
|----|------|--------|---------------|
| S8-1 | chore | **Receber o contrato do agente** e versioná-lo em `docs/agent/contrato.md` | Arquivo no repositório. **Bloqueia o resto da sprint** |
| S8-2 | chore | Conjunto de avaliação: perguntas de controle com resposta esperada (reunião curta, de 2 h, pergunta sem resposta na reunião) rodando contra o agente atual | Linha de base registrada antes da migração |
| S8-3 | refactor | Chat como grafo: selecionar trechos → responder → verificar o contrato → refazer ou responder "não foi mencionado" | Mesma porta `ILLMService`; casos de uso sem mudança; avaliação igual ou melhor |
| S8-4 | refactor | Resumo como grafo: dividir → resumir partes → reunir → validar o JSON → refazer a parte que falhou | Reunião de 2 h sem erro; nenhum resumo com JSON inválido |
| S8-5 | chore | Remover o que sobrar do LangChain e travar `langgraph` no `requirements.in` | Build e CI verdes; imagem não cresce sem motivo |

Saída: avaliação com o contrato respeitado em todas as perguntas de controle e sem regressão
frente à linha de base.

## Sprint 9 — Concorrência e fila para N usuários (ADR-015)

**Implementada em 2026-11-15**, medida no host (Docker em manutenção); números e desvios na ADR-015.
Justiça ficou por prioridade na fila, não por limite K por usuário. Falta validar no compose
(`worker-transcribe`/`worker-llm`, `--scale`) e com duas reuniões reais ao mesmo tempo (S9-5).

Objetivo: com vários usuários ao mesmo tempo, ninguém espera atrás da reunião longa de outro e a
API continua respondendo rápido.

Estado medido em 2026-11-15: a API roda num processo; o worker de processamento e o do bot rodam
um trabalho por vez; o Ollama atende um pedido por vez. Nada se perde (a fila é o Redis), mas
o tempo de espera cresce em fila única: uma reunião de 2 h segura todas as outras.

| Id | Tipo | Tarefa | Pronto quando |
|----|------|--------|---------------|
| S9-1 | chore | Teste de carga com N usuários simulados (envio de áudio, bot, chat, consultas de status) | Números de base na ADR-015: latência da API, espera na fila, vazão |
| S9-2 | feat | Filas por etapa: transcrição, LLM e bot, cada uma com seus workers e concorrência própria; workers escaláveis no compose (`--scale`) | Transcrição de um usuário não espera o resumo de outro |
| S9-3 | feat | Justiça entre usuários: limite de trabalhos em andamento por usuário e limite de pedidos por minuto na API | Um usuário com 10 envios não atrasa o primeiro envio de outro |
| S9-4 | feat | API com vários processos (`uvicorn --workers`) e chat com limite de chamadas simultâneas ao LLM | p95 das rotas de leitura abaixo da meta da ADR-015 sob carga |
| S9-5 | feat | Vários bots em paralelo: um worker por perfil de Chrome (`BOT_PROFILES`) | Duas reuniões gravadas ao mesmo tempo |
| S9-6 | feat | Posição na fila em `GET /meetings/{id}/status` | O front mostra "3º na fila" |

Saída: o teste de carga com a meta da ADR-015 passa, sem tarefa perdida e sem dado cruzado entre usuários.

## Sprint 10 — Windows via Docker (ADR-016)

**Estado em 2026-11-15** (Docker em manutenção): S10-2 a S10-5 feitas sem Docker. O script de
backup foi validado contra um Mongo de rascunho no host (backup, retenção, restauração com
`--drop`); o serviço `backup` rodou no compose depois que o Docker voltou. S10-1: imagem do bot construída,
login do Google feito pelo noVNC, fumaça verde e reunião completa até o resumo no container;
falta o teste num Windows. O job de Windows do CI roda no próximo push.

Objetivo: subir o sistema completo numa máquina Windows só com Docker Desktop, seguindo o README.

| Id | Tipo | Tarefa | Pronto quando |
|----|------|--------|---------------|
| S10-1 | feat | Bot em container: Chromium com tela virtual, perfil do bot num volume, login feito uma vez pelo navegador (noVNC) | Bot grava uma reunião sem nada instalado no host além do Docker |
| S10-2 | chore | `.gitattributes` com fim de linha LF para scripts e arquivos de container | Clone no Windows sobe sem erro de `\r` |
| S10-3 | chore | Backup e restauração como comandos do compose (sem `bash` no host) | Mesmo comando no Windows, macOS e Linux |
| S10-4 | chore | CI com job em Windows para os testes unitários | CI verde em `windows-latest` |
| S10-5 | chore | README para Windows: WSL2, onde clonar (dentro do WSL2, por desempenho), Ollama no host | Alguém sobe o ambiente no Windows só com o README |

Saída: Windows 11 com Docker Desktop, do clone à reunião resumida, sem passo fora do README.

## Versão 1.0.0 — fechada em 2026-11-16 (produção local)

Notas em `CHANGELOG.md`. Fecha as Sprints 0 a 10 (com as pendências de validação real anotadas
em cada uma) e as entregas de 15-16/11: credenciamento do bot, ações do chat, observabilidade,
memória entre reuniões, agenda (aguardando credenciais), acesso pela rede local, correções de
latência do LLM, da corrida chat × resumo, dos participantes e do acompanhamento de etapas.
A Sprint 11 (servidor com HTTPS) fica para a v1.1.

## Sprint 11 — Versão 1.0 em produção

**Preparado em 2026-11-15, sem servidor:** `docker-compose.prod.yml` + `deploy/Caddyfile` (S11-2;
config do compose conferida, Caddy não executado), cookie `Secure` sob HTTPS, checklist em
`docs/seguranca.md` (S11-3), `/health` com workers e `scripts/health_alert.py` (S11-4; testados
no host), roteiro `docs/operacao.md` e rascunho do `CHANGELOG.md` (S11-6). Trava por link no envio
do bot (corrida que a API em 2 processos tornou provável), testada entre processos no Redis.

| Id | Tipo | Tarefa | Pronto quando |
|----|------|--------|---------------|
| S11-1 | chore | Servidor limpo a partir do repositório (critério de saída da Sprint 3) | `docker compose up` num servidor novo |
| S11-2 | chore | HTTPS e domínio com proxy reverso; `ALLOWED_ORIGINS` do front | Certificado válido; API só por HTTPS |
| S11-3 | chore | Segredos fora do repositório; cadastro fechado (`ALLOW_REGISTRATION=false`); `API_KEY` trocada | Checklist de segurança assinado |
| S11-4 | chore | Backup agendado e restauração testada no servidor; alerta quando `/health` falhar | Restauração cronometrada; alerta recebido num teste |
| S11-5 | chore | Teste de carga da Sprint 9 contra o servidor | Meta da ADR-015 atingida em produção |
| S11-6 | chore | Tag `v1.0.0`, notas da versão e roteiro de operação (restaurar, trocar chave, reiniciar bot) | Tag publicada |

Saída: v1.0.0 no ar, com usuários reais gravando reuniões.

## Feature: memória e contexto do agente (ADR-022) — Sprints 12 a 16

Objetivo: o agente não perde contexto em reuniões longas, liga reuniões diferentes pelo mesmo tópico e
pelas mesmas pessoas, responde de forma didática, cita de onde tirou cada fato e pergunta o que ficou em
aberto. Funciona igual em qualquer provider com pelo menos a capacidade do modelo atual
(`qwen2.5:7b`, 32k de janela): trocar de provider é `.env`, não código.

Portão de qualidade de todas as sprints: `scripts/eval_agent` ampliado (S12-4), rodado no modelo piso.
Uma sprint só fecha se não piorar nenhuma nota da anterior e se a latência ficar dentro do teto anotado.
Tudo atrás da flag `MEMORY_V2` até a Sprint 16.

## Sprint 12 — Harness adaptável e linha de base

**Andamento (2026-11-21):** ADR-022 aceita. S12-3 entregue: porta `IEmbedder` (`domain/interfaces/embedder.py`),
ONNX no processo como padrão (`infrastructure/embeddings/`), adaptadores Ollama e OpenAI, sem dependência
nova; paráfrase em português conferida com o modelo real e medições na ADR-022.
S12-1, S12-2 e S12-5 entregues: `ModelProfile` lido do `.env` (`LLM_CONTEXT_TOKENS`, `LLM_NATIVE_TOOLS`,
`LLM_JSON_MODE`, `OPENAI_BASE_URL` para qualquer servidor compatível); ferramentas por JSON quando o modelo
não tem chamada nativa; `ContextBudget` com o que é da pergunta (trechos, outras reuniões, notas) na
mensagem dela, para o prompt de sistema não mudar entre perguntas. S12-4: `eval_agent` v2 com três
reuniões ligadas; linha de base em `docs/eval/linha-de-base.md`.

| Id | Tipo | Tarefa | Pronto quando |
|----|------|--------|---------------|
| S12-1 | feat | `ModelProfile` por provider/modelo (janela, ferramenta nativa, modo JSON, embeddings), lido do `.env`; `ModelClient` decide pelo perfil | Ollama, OpenAI e OpenRouter rodam o mesmo grafo só trocando o `.env` |
| S12-2 | feat | Saída estruturada validada por esquema, com uma tentativa de reparo; ferramenta por JSON quando não há chamada nativa | Resumo e ferramentas passam no modelo piso sem regressão no `eval_agent` |
| S12-3 | feat | Porta `IEmbedder`; padrão ONNX no processo (`intfloat/multilingual-e5-small`, igual em Linux, macOS e Windows), adaptadores Ollama e OpenAI; vetor guarda o nome do modelo | Similaridade em português conferida com o modelo real; memória e tempo no M4 16 GB anotados na ADR-022 |
| S12-4 | test | `eval_agent` v2: 3 reuniões sintéticas ligadas (mesmas pessoas e tópicos), perguntas de continuidade, citação, didática e pergunta em aberto; mede acerto e latência | Linha de base gravada em `docs/` para o modelo piso |
| S12-5 | feat | `ContextBudget`: blocos com teto (contrato, procedural, reunião, longa, curta, pergunta, resposta), prefixo estável primeiro | Prompt montado pelo orçamento; cache de prefixo do Ollama mantido entre perguntas (medido) |

Saída: mesma qualidade de hoje no modelo piso, provider trocável por configuração, linha de base medida.

## Sprint 13 — Memória curta e memória longa

**Andamento (2026-11-21):** S13-1 a S13-5 entregues. Trechos por fala com vetor em `data/index`
(`use_cases/meeting_index.py`, `infrastructure/index_store.py`), indexados ao fim do resumo e refeitos se a
transcrição mudar; `scripts/reindex_memory`. Busca híbrida (palavra + vetor por RRF) no chat de reunião longa,
com volta à busca por palavra se o índice falhar: a paráfrase do eval (2 h, ~96 mil caracteres) é achada pela
híbrida e não pela palavra. Entidades por dono (pessoas com apelidos; tópicos pelo limiar 0,93 calibrado no
e5-small). Memória curta: até 40 trocas na íntegra pelo orçamento da janela, o resto em resumo corrido que
preserva as mensagens do usuário. Isolamento por dono e exclusão junto com a reunião testados.

| Id | Tipo | Tarefa | Pronto quando |
|----|------|--------|---------------|
| S13-1 | feat | Trechos por fala (orador, horário, sobreposição) com embedding, gravados ao fim da transcrição (`chunks`, por dono) | Reunião nova indexada sozinha; script de reindexação para as antigas |
| S13-2 | feat | Entidades e menções a partir do resumo: pessoas (com apelidos), tópicos (agrupados por similaridade), decisões e tarefas | Mesma pessoa/tópico em duas reuniões aparece como a mesma entidade no teste |
| S13-3 | feat | Busca híbrida (palavra + vetor) dentro da reunião aberta, no lugar de `select_relevant` | Pergunta parafraseada acha o trecho certo em reunião de 2 h (caso no eval) |
| S13-4 | feat | Memória curta: últimos turnos na íntegra + resumo corrido dos anteriores dentro do teto | Conversa de 40 perguntas não estoura a janela nem esquece o que foi combinado no início |
| S13-5 | test | Isolamento: índice nunca devolve trecho de outro dono | Teste de dois usuários verde |

Saída: reuniões longas sem perda de contexto no chat; entidades ligando reuniões.

## Sprint 14 — RAG entre reuniões e CAG

**Andamento (2026-11-21):** S14-1 a S14-5 entregues. Falas de outras reuniões do dono entram com a citação
`[Título · data · horário]`, ordenadas por relevância (palavra + vetor), reuniões ligadas por entidade e
recência (`MeetingIndex.search_many`). Ferramenta `search_meetings` com uma rodada só (sem laço). CAG:
respostas por pergunta normalizada, escopo dono + geração (`use_cases/agent_cache.py`), invalidadas por
qualquer gravação de reunião ou nota do dono; camada quente dos índices na memória do processo, validada pela
data do arquivo; Redis no collab, processo no solo (`infrastructure/hot_cache.py`). Caminho de cada resposta
(cache, quente, banco) com p50/p95 no painel de Observabilidade (só no collab, onde há Redis para as métricas).

| Id | Tipo | Tarefa | Pronto quando |
|----|------|--------|---------------|
| S14-1 | feat | Recuperação entre reuniões do dono: trechos + expansão por entidades, ordem por relevância, recência e estado da decisão; resposta cita título, data e horário | Perguntas de continuidade do eval respondidas com citação correta |
| S14-2 | feat | Ferramenta `search_meetings` para o agente aprofundar a busca quando o contexto não bastar | Agente usa a ferramenta nos casos do eval que pedem outra reunião |
| S14-3 | feat | CAG: camada quente com os dados recém-gerados (Redis no collab, processo no solo), escrita junto com o banco; cache de respostas por pergunta equivalente no mesmo escopo; invalidação por reunião nova, resumo ou tarefa alterados | Pergunta repetida volta do cache; dado novo invalida; teste de invalidação verde |
| S14-4 | feat | Roteador CAG → trechos quentes → RAG no banco, com métricas (acerto do cache, latência por caminho) na Observabilidade | Painel mostra taxa de acerto e p50/p95 por caminho |
| S14-5 | test | Isolamento por dono também no cache | Teste de dois usuários verde |

Saída: perguntas entre reuniões respondidas com fonte; resposta repetida sem ir ao banco.

## Sprint 15 — Memória procedural e contrato v2 (agente didático)

**Andamento (2026-11-22):** S15-1 a S15-5 entregues. Contrato v2 aprovado e ligado pela flag `MEMORY_V2`
(chat com o compacto; resumo com o completo, ou o compacto em janela abaixo de 16k). Notas do usuário no prefixo
estável; intenção da pergunta (fato, entre reuniões, análise, pendências) sem chamar o modelo; verificação de
origem das citações e de datas fora do contexto; resumo com contribuições por orador, tópico → decisão e
questões em aberto (inspetor de Gravações); citações clicáveis que abrem a reunião no trecho e "Perguntas para
você" como botões (conferido no navegador). Eval 19/22 em `docs/eval/sprint-15.md`.

**Andamento (2026-11-21):** S15-2 escrito, aguardando revisão do dono do contrato: `SPEC_CONTRACT_V2.md`
(completo, para o resumo; numeração do v1 mantida, §19 e §20 novos) e `SPEC_CONTRACT_CHAT_V2.md`
(compacto, ~2,2 mil tokens contra ~8,3 mil do atual). Ainda não ligados ao agente: entram na S15-3 com o
`eval_agent`. Invariantes em `test/test_contract_v2.py`.

| Id | Tipo | Tarefa | Pronto quando |
|----|------|--------|---------------|
| S15-1 | feat | Memória procedural: notas de `remember`, preferências de formato e glossário da organização, no prefixo estável; gerência em Minha conta | Preferência gravada muda o formato das próximas respostas (eval) |
| S15-2 | docs | Contrato v2 (SPEC): receptividade e didática, análise por fala, mapa tópico → decisão, perguntas sobre o que ficou em aberto, regras de citação; versão compacta para o chat | Aceite do dono do contrato; contrato do chat cabe no teto do bloco |
| S15-3 | feat | Grafo do chat: classificar a intenção (fato, entre reuniões, análise, pendências) → recuperar (CAG/RAG) → responder → verificar → perguntar ao usuário quando faltar informação | Verificação reprova afirmação sem fonte; pergunta de esclarecimento nos casos ambíguos do eval |
| S15-4 | feat | Resumo passa a gravar contribuições por orador, mapa tópico → decisão e questões em aberto (alimentam a memória longa) | Campos novos no resumo e no inspetor de Gravações |
| S15-5 | feat | Interface: citações clicáveis (reunião e horário) e perguntas do agente no chat do Estúdio e de Gravações | Clique na citação abre a reunião no trecho |

Saída: respostas didáticas, com fonte, que apontam o que falta decidir.

## Sprint 16 — Portabilidade, desempenho e entrega

**Andamento (2026-11-22):** S16-1 a S16-4 entregues, com dois limites: na matriz, o modelo local maior e o
por API não foram medidos (sem disco, sem chave); a reindexação "em produção" (S16-3) fica para quando os
containers forem reconstruídos (disco). Streaming no chat de Gravações; medições e desvios na ADR-022.

| Id | Tipo | Tarefa | Pronto quando |
|----|------|--------|---------------|
| S16-1 | test | Matriz de providers com o mesmo harness: modelo piso local, um modelo local maior e um por API | Notas do eval por modelo registradas, sem mudança de código entre eles |
| S16-2 | perf | Memória e tempo no M4 16 GB (LLM + embeddings + Whisper), resposta em streaming (proposta da ADR-021) | Primeiras palavras em segundos; sem swap novo além do medido na S12-3 |
| S16-3 | chore | Reindexação das reuniões existentes em produção, flag `MEMORY_V2` ligada, operação documentada (reindexar, limpar cache) | `docs/operacao.md` atualizado; flag ligada sem regressão |
| S16-4 | docs | ADR-022 aceita com "Como ficou" e desvios; notas de versão | CHANGELOG com a versão |

Saída: versão com a memória nova ligada em produção.

## Depois da 1.0

- Discord por bot oficial (era S6-6; ADR-012).
- Mais de uma organização (times com reuniões compartilhadas).
- O front novo em si: o contrato está em `docs/api/openapi.json` (ADR-013).
