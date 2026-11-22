# Mapa: rotas da FastAPI → interface nova (`frontend/`)

Fonte: `docs/api/openapi.json` (44 rotas). O front chama tudo por `frontend/src/api/endpoints.ts`,
sempre em `/api/...` na mesma origem: o Vite (desenvolvimento) e o Caddy do container `web`
(produção) repassam `/api/*` para a FastAPI sem o prefixo. Não há CORS nem chave no navegador:
cada pedido leva `Authorization: Bearer <token>` da sessão.

## Usadas pela interface

| Rota | Onde |
|---|---|
| `GET /config` | Partida do app: modo (solo/collab), cadastro aberto, e-mail, agenda, formatos e limite de upload |
| `POST /auth/login` · `POST /auth/register` | Tela de login (AI MEET): entrar e criar conta |
| `POST /auth/password/forgot` · `POST /auth/password/reset` | Login → Esqueci a senha |
| `GET /auth/me` · `POST /auth/logout` | Sessão salva ao abrir o app; Encerrar sessão / Trocar conta |
| `POST /auth/password` | Minha conta → Trocar senha |
| `GET /auth/sessions` · `DELETE /auth/sessions/{sid}` · `DELETE /auth/sessions` | Minha conta → Sessões abertas |
| `GET /admin/users` · `POST /admin/sessions/purge` | Minha conta → Administração (só admin) |
| `POST /admin/mode` | Barra lateral → Mudar para solo/colaborativo (só admin) |
| `GET /bot/status` · `POST /bot/setup` | Estúdio → Enviar bot (credenciamento) |
| `GET /calendar/events` | Estúdio → Próximas reuniões da agenda (com `ENABLE_CALENDAR`) |
| `POST /meetings/bot` | Estúdio → Enviar bot para a reunião (e "Mandar" da agenda) |
| `POST /meetings/upload` | Estúdio → Nova reunião (modo solo) |
| `GET /meetings/` | Estúdio (reunião acompanhada) e Gravações (lista) |
| `GET /meetings/{id}` | Gravações → inspetor; Estúdio → transcrição final e histórico do chat |
| `GET /meetings/{id}/status` | Gravações → andamento enquanto processa |
| `GET /meetings/{id}/live` | Estúdio → Transcrição em tempo real (etapa Transcrevendo) |
| `POST /meetings/{id}/process` · `POST /meetings/{id}/resume` | Gravações → Reprocessar áudio / Retomar |
| `DELETE /meetings/{id}` | Gravações → Excluir |
| `PATCH /meetings/{id}/tasks/{index}` · `POST /meetings/{id}/tasks/email` | Gravações → Itens de ação |
| `GET /meetings/{id}/export.md` | Gravações → Resumo (.md) |
| `POST /meetings/{id}/chat` · `DELETE /meetings/{id}/chat` | Estúdio (orbe) e Gravações → Chat do agente |
| `POST /meetings/{id}/actions/{aid}/send` · `.../cancel` · `GET .../document` | Chat → e-mail preparado e documento gerado |
| `GET /memory/` · `DELETE /memory/{note_id}` | Minha conta → Memória do agente |
| `GET /observability/summary` · `GET /observability/logs` | Observabilidade (só admin) |
| `GET /observability/meetings/{id}` | Gravações → Diagnóstico (só admin) |

## Fora da interface, de propósito

| Rota | Por quê |
|---|---|
| `POST /capture/chunk` · `POST /capture/finalize` · `GET /capture/status` | Uso interno do bot (token HMAC por gravação) |
| `GET /health` | Healthcheck do compose e de monitoramento externo; a tela usa `/observability/summary` |
| `GET /observability/metrics` | Formato Prometheus, para coletor externo |

## Telas e rotas do front

| Caminho | Tela |
|---|---|
| (sem sessão) | Login AI MEET com o robô 3D: entrar, criar conta, esqueci a senha |
| `/estudio` | Bot, upload (solo), status da reunião, transcrição ao vivo, chat |
| `/gravacoes`, `/gravacoes/:id` (`?aba=chat`) | Biblioteca, inspetor, chat completo, diagnóstico |
| `/observabilidade` | Painel do admin |
| `/conta` | Minha conta (abre pelo nome do usuário na barra lateral) |
