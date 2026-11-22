# Roteiro de operação (S11-6)

Comandos para o servidor da 1.0. Em produção, todo `docker compose` leva os dois arquivos:

```bash
alias dc='docker compose -f docker-compose.yml -f docker-compose.prod.yml'
```

Na máquina local, sem HTTPS, basta `docker compose`.

## Subir, atualizar, conferir

```bash
dc run --rm backup                              # sempre antes de atualizar
git pull && dc up -d --build --remove-orphans
curl -s https://api.$DOMAIN/health              # 200 e tudo "ok"; "bot" só informa
```

Em `/health`, `worker_transcribe` ou `worker_llm` com "sem worker" significa que as reuniões
estão paradas na fila. Veja os logs com `dc logs --tail 100 worker-transcribe worker-llm` e, se
for o caso, rode `dc up -d`. Toda linha de log traz o id da reunião:
`dc logs worker-transcribe worker-llm | grep <id>`.

## Restaurar o banco

1. Pare quem escreve: `dc stop api web worker-transcribe worker-llm`.
2. Restaure: `dc run --rm backup restore backups/mongo-<data>.archive.gz`. As coleções do backup
   **substituem** as atuais.
3. Suba de novo: `dc up -d` e confira o `/health`.

A gravação de áudio não está no backup do banco. Uma reunião restaurada sem áudio em
`data/audio/` não pode ser reprocessada, mas o resumo e a transcrição estão no banco.

## Trocar a API_KEY

O token de captura do bot é derivado da chave. **Trocar a chave durante uma gravação faz o bot
perder o resto do áudio daquela reunião.**

1. Confira que nenhuma reunião está gravando (interface, Estúdio: status da reunião acompanhada).
2. Gere a chave nova: `python -c "import secrets; print(secrets.token_urlsafe(32))"` e grave no `.env`.
3. `dc up -d` para recriar os containers com a chave nova. Reinicie também o worker do bot.
4. Avise quem usa a chave de serviço (scripts e integrações).

Sessões de usuário não dependem da chave e continuam valendo.

## Reiniciar o bot

- No host (hoje): pare o processo com Ctrl+C e rode `python main.py --bot-worker`. Para mais de
  um bot, rode um processo por perfil (`BOT_CHROME_PROFILE=<pasta>`).
- Login do Google expirado (o bot para na tela de entrar da conta, visível com `BOT_HEADLESS=false`): rode
  `python -m infrastructure.recorder.bot_setup` e entre de novo na conta do bot.
- Fumaça depois de mexer no bot: `python -m infrastructure.recorder.run_bot --url <link> --smoke 30`.

## Reunião parada ou com erro

- Com `status=error`, a mensagem aparece na interface e o botão "Reprocessar áudio gravado" (ou
  `POST /meetings/{id}/process`) refaz transcrição e resumo.
- Se ficou em `transcribing` ou `summarizing` porque o worker foi morto com `kill -9`, a tarefa só
  volta para a fila depois de 6 h (ADR-015). Reprocesse para não esperar.
- Se o bot morreu durante a gravação, o áudio gravado até ali é processado. Se a reunião ficou
  em `recording`, use "Reprocessar".

## Memória do agente (ADR-022)

- Trechos com vetor e entidades ficam em `data/index` (um arquivo por reunião e um por dono). Cada reunião
  é indexada ao terminar o resumo; se a transcrição mudar, o índice é refeito na próxima pergunta.
- Reuniões gravadas antes da memória, ou depois de trocar `EMBEDDING_MODEL`: o próprio `dc up -d` indexa
  (serviço `memory-index`, que roda e termina; ver `dc logs memory-index`). À mão:
  `dc run --rm memory-index` (no solo, `python -m scripts.reindex_memory`).
- Na primeira indexação o modelo de embeddings (~470 MB) é baixado para o cache do Hugging Face.
- Ligar na produção (S16-3): `MEMORY_V2=true` no `.env` e `dc up -d --build --remove-orphans` (constrói,
  sobe e indexa); depois, se quiser, `python -m scripts.eval_agent` para comparar com `docs/eval/`. Algo
  piorou: `MEMORY_V2=false` e `dc up -d` voltam ao agente da v1.0 sem perder dados (o índice fica em disco).
- Apagar o índice (por exemplo, para trocar de modelo de embeddings): parar os serviços, apagar
  `data/index` e rodar a reindexação.
- Se o índice falhar, o chat continua com a busca por palavra; o erro fica no log do worker.
- Cache de respostas (CAG): invalida sozinho a cada gravação de reunião ou nota do dono e expira em 24 h.
  Para limpar tudo no collab: `dc exec redis sh -c "redis-cli --scan --pattern 'cag:*' | xargs -r redis-cli del"`
  (no solo, reiniciar a API). O painel de Observabilidade mostra acerto do cache e p50/p95 por caminho.

## Contas

- Feche o cadastro depois de criar as contas: `ALLOW_REGISTRATION=false` no `.env` e `dc up -d`.
- O admin (a primeira conta) limpa sessões em "👤 Minha conta"; a limpeza nunca apaga usuários nem reuniões.
- Senha esquecida: o próprio usuário usa "Esqueci a senha" (exige SMTP).

## Alerta

Cron do servidor, a cada 5 minutos, com `ALERT_EMAIL` e o SMTP no `.env`:

```
*/5 * * * * cd /srv/meet-agent && .venv/bin/python -m scripts.health_alert https://api.DOMINIO/health
```

O script manda um e-mail quando a API cai e outro quando volta.

## Backup agendado

```
30 3 * * * cd /srv/meet-agent && docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm backup
```

Copie `backups/` para fora do servidor. Um backup que só existe na mesma máquina não protege
contra a perda do disco.
