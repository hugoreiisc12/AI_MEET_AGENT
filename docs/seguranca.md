# Checklist de segurança da 1.0 (S11-3)

Marque cada item **no servidor**, antes de abrir para usuários reais. "Conferido" indica o que já
foi verificado no repositório em 2026-11-15; o resto só se confere na implantação.

| # | Item | Como conferir | Estado |
|---|------|---------------|--------|
| 1 | Nenhum segredo no git (`.env`, credenciais do Google, tokens) | `git ls-files \| grep -iE "\.env$\|credentials\|token"` vazio; varredura por chaves no código | Conferido no repositório |
| 2 | `.env` do servidor só legível pelo dono | `chmod 600 .env` | Servidor |
| 3 | `API_KEY` nova, gerada no servidor, diferente da de desenvolvimento | Roteiro em `docs/operacao.md` | Servidor |
| 4 | Cadastro fechado depois de criar as contas | `ALLOW_REGISTRATION=false`; `GET /config` com `registration_open: false` | Servidor |
| 5 | Só 80 e 443 abertos; Mongo, Redis, API e interface (`web`) sem porta no host | `docker-compose.prod.yml` (`ports: !reset []`); `ss -tlnp` no servidor | Compose conferido (`config`); servidor |
| 6 | HTTPS com certificado válido em `DOMAIN` e `api.DOMAIN` | Abrir no navegador; `curl -I http://...` redireciona para https | Servidor |
| 7 | Cookie de sessão com `Secure` | No navegador: DevTools → Application → Cookies → `meet_agent_session` | Automático sob HTTPS; conferir no servidor |
| 8 | CORS só para o domínio da interface | `ALLOWED_ORIGINS` vem do `DOMAIN` no compose de produção | Compose conferido |
| 9 | Senhas com scrypt; token de sessão guardado só como hash; bloqueio após 5 erros | ADR-011; testes em `test/test_api.py` | Conferido (testes) |
| 10 | Limite de pedidos por usuário ativo | `RATE_LIMIT_PER_MINUTE` > 0; 31º envio no minuto devolve 429 | Conferido no host (ADR-015) |
| 11 | Backup agendado, copiado para fora do servidor, restauração testada | `docs/operacao.md` | Servidor |
| 12 | Alerta de API fora do ar chegando | Parar `worker-llm` e esperar o e-mail do `health_alert` | Servidor |
| 13 | Conta do bot exclusiva para o bot (não a conta pessoal de ninguém) | O perfil do Chrome do bot fica em volume/pasta própria | Servidor |
| 14 | SMTP com senha de app, não a senha da conta | Gmail: myaccount.google.com/apppasswords | Servidor |
| 16 | Índice da memória do agente (`data/index`: trechos da transcrição e entidades) com o mesmo cuidado das reuniões | Fica no volume `./data` (backup junto); separado por dono; sai junto quando a reunião é apagada (`test/test_meeting_index.py`) | Conferido (testes) |
| 15 | `BOT_GOOGLE_PASSWORD` só se o login automático do bot for usado; conta do bot sem dados pessoais | Preferir o login pela tela do bot (noVNC) e deixar a senha fora do `.env` | Servidor |

Riscos aceitos, registrados para revisão:
- A interface nova guarda o token da sessão no `localStorage` do navegador (envia como
  `Authorization: Bearer`), então ele não tem `HttpOnly`. Um XSS poderia ler o token. Mitigação:
  o React escapa o texto (nenhum HTML vindo de usuários é inserido na página), o token é revogável
  em "Minha conta" → Sessões abertas, e expira em `SESSION_DAYS`. Para eliminar o risco, trocar
  por cookie `HttpOnly` emitido pela API.
- A chave de serviço (`X-API-Key`) enxerga todas as reuniões. Use só em scripts do próprio servidor.

Assinatura: ______________________  Data: ____/____/______
