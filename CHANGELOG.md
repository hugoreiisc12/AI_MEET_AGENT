# Notas de versão

## v1.1.0 — 2026-11-22 (memória do agente, ADR-022)

Interface nova em React no lugar do Streamlit (container `web`, porta 8080) e o agente com memória.
Avaliação no modelo local (`qwen2.5:7b`): 13/16 → 19/22 checagens.

### O que mudou
- **Interface nova** (React/Vite): Estúdio Ao Vivo, Gravações, Observabilidade e Minha conta; login nos dois
  modos; tema claro e escuro; transcrição ao vivo durante a transcrição; troca solo/colaborativo para o admin.
- **Memória do agente:** acha a resposta mesmo com outras palavras (busca por significado), liga reuniões
  pelas mesmas pessoas e tópicos e cita falas de outras reuniões com título, data e horário; lembra
  preferências; conversa longa sem perder o que foi combinado no início.
- **Respostas mais rápidas:** pergunta repetida volta do cache; perguntas seguidas na mesma reunião
  reaproveitam o prompt; primeiras palavras aparecem enquanto o agente escreve (chat de Gravações).
- **Agente mais didático (contrato v2):** "Perguntas para você" sobre o que ficou em aberto, resumo com
  contribuições de cada participante, mapa tópico → decisão e questões em aberto.
- **Citações clicáveis:** abrem a reunião no trecho citado.
- **Qualquer provider de LLM** pelo `.env` (Ollama, OpenAI, OpenRouter ou servidor compatível), com
  ferramentas por JSON quando o modelo não tem chamada nativa.
- **Mais verificação:** reunião, horário e autor de cada citação; datas fora do contexto; nota de memória
  que o usuário não pediu.

### Para atualizar
- `MEMORY_V2=true` (padrão). Um comando só: `docker compose up -d --build --remove-orphans` constrói, sobe e
  indexa as reuniões antigas (serviço `memory-index`).
- O modelo de embeddings (~470 MB) é baixado na primeira indexação.
- Voltar ao agente da 1.0 sem perder dados: `MEMORY_V2=false`.


## v1.0.0 — 2026-11-16 (produção local)

Primeira versão fechada. Roda completa com Docker numa máquina (macOS validado; Windows com
Docker Desktop preparado, sem teste real). A implantação num servidor com HTTPS está pronta no
repositório (`docker-compose.prod.yml`, `docs/operacao.md`, `docs/seguranca.md`), mas não foi feita:
é a Sprint 11.

### O que a 1.0 faz
- **Bot nas reuniões**, em container: entra no Google Meet pelo link, espera ser admitido, grava o
  áudio e registra quem estava e quem falou (legendas do Meet). Sai 50 s depois de ficar sozinho.
  Credenciado pela interface (botão "Credenciar bot"). Zoom e Teams: escritos, **não validados**.
- **Transcrição e resumo** (Whisper local + LLM local): visão geral, tópicos, tarefas com
  responsável, decisões com estado (aprovada, proposta, pendente…), seguindo o contrato do agente.
- **Chat sobre a reunião**, verificado contra a transcrição antes de responder (avaliação do
  contrato: 3/8 → 7-8/8), com **ações**: e-mail (só para endereço que o usuário escreveu e só com
  confirmação), documentos em PDF, Word, Excel, CSV, HTML com gráficos e Markdown, e notas de memória.
- **Memória entre reuniões** (§14): decisões e pendências das outras reuniões do mesmo usuário,
  com origem e data, e preferências que o usuário pede para lembrar.
- **Contas**: cadastro, login, sessões, recuperação de senha por e-mail, admin; cada usuário vê só
  as próprias reuniões; mesmo link para duas pessoas = uma gravação, duas reuniões.
- **Vários usuários ao mesmo tempo**: filas separadas para transcrição e resumo, prioridade justa,
  posição na fila, limite de pedidos por minuto.
- **Acompanhamento**: tempo de cada etapa, quanto ela costuma levar, aviso e botão "Retomar"
  quando uma etapa trava (worker reiniciado no meio).
- **Observabilidade**: métricas (JSON e Prometheus), logs de todos os serviços num lugar só,
  linha do tempo por reunião, saúde dos workers por batimento.
- **Agenda do Google** (opcional): próximas reuniões com "Mandar o bot"; aguardando as credenciais.
- **Rede local**: interface e API acessíveis de outros aparelhos; banco e fila só na máquina.
- **API para um front novo**: contrato OpenAPI em `docs/api/openapi.json`.

### Corrigido nesta versão (achados em uso)
- Pergunta no chat durante o resumo apagava o resumo (e o resumo apagava perguntas).
- Botões do Meet ("Aumentar zoom", "Liberar a apresentação…") viravam participantes.
- `/health` dava "sem worker" durante todo trabalho normal.
- Transcrição vazia com o bot em container (filtro anti-alucinação descartava fala nítida).
- Demora do LLM: janela de contexto variável recarregava o modelo (~50 s por troca).

### Limites conhecidos
- Máquina com 16 GB fica em swap com Ollama + Whisper + Docker: transcrição e respostas lentas.
  Propostas na ADR-021 (Ollama com flash attention e cache q8, Whisper `small`, contrato compacto).
- O bot enxerga o nome de exibição, não o e-mail; fala sem legenda fica como "Speaker N".
- Discord depois da 1.0 (exige bot oficial). Sem HTTPS fora do compose de produção.

### Atualizando a partir da versão de desenvolvimento
- `docker compose up -d --build --remove-orphans` (o serviço `worker` virou `worker-transcribe` e `worker-llm`).
- Backup: `docker compose run --rm backup`.
- Credenciais do Google ficam em `data/google/` (fora do git).
