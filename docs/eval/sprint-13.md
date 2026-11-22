# Linha de base do agente — 21/11/2026

Modelo: `ModelProfile(provider='ollama', model='qwen2.5:7b', context_tokens=32768, native_tools=True, json_mode=True)` · contrato: `SPEC_CONTRACT.md`

**14/18 checagens** · p50 12 s · p95 29 s

Prompt = tokens do prompt e tempo de leitura no Ollama. O Ollama conta também o que veio do cache;
o tempo mostra o cache: prefixo reaproveitado lê em ~1 s, sem cache leva dezenas de segundos.

| Suíte | Regra | Resultado | Tempo | Prompt |
|---|---|---|---|---|
| v1 | resumo | ok | 29 s | 6647 em 9.8 s |
| v1 | §7 decisão aprovada | ok | 21 s | 7618 em 19.1 s |
| v1 | §4 proposta ≠ decisão | falha: faltou o termo esperado | 20 s | 7845 em 1.1 s |
| v1 | §7 responsável só se atribuído | ok | 3 s | 7623 em 0.3 s |
| v1 | §4/§16 não preencher lacunas | ok | 1 s | 7620 em 0.4 s |
| v1 | §7 compromisso explícito | ok | 2 s | 7621 em 0.4 s |
| v1 | §4 não presumir concordância | ok | 6 s | 7617 em 0.4 s |
| v1 | §11 avaliação crítica | ok | 26 s | 7615 em 0.4 s |
| v2 | §14 continuidade | ok | 27 s | 7861 em 15.8 s |
| v2 | §3.7 didática | ok | 12 s | 7966 em 5.0 s |
| v2 | §20 citação da reunião aberta | ok | 7 s | 7855 em 4.1 s |
| v2 | §14 decisão revista depois | ok | 26 s | 8040 em 18.3 s |
| v2 | §14 pendência resolvida depois | falha: faltou um de ['Bruno']; faltou o termo esperado | 10 s | 8042 em 3.9 s |
| v2 | §7 decisão condicionada | ok | 18 s | 7751 em 14.4 s |
| v2 | §10.1 perguntas para você | falha: não casou /\?/ | 11 s | 7749 em 0.5 s |
| v2 | §4 não misturar reuniões | ok | 4 s | 7861 em 3.3 s |
| v2 | S13-3 busca acha o trecho da paráfrase | ok | 4 s | - |
| v2 | §5 paráfrase em reunião de 2 h (S13-3) | falha: faltou um de ['12 mil'] | 45 s | 10713 em 43.5 s |

## Leitura (2026-11-21, depois da Sprint 13, contrato v1)

- **Busca híbrida:** na reunião de 2 h, o trecho com a resposta é o primeiro do contexto; a busca por
  palavra (antiga) não o encontra. Isso fecha o critério da S13-3.
- **O modelo piso não usa o trecho:** com o trecho certo no contexto, o `qwen2.5:7b` respondeu "Isso não foi
  mencionado" porque não ligou "serviço de mensageria" a "fornecedor da fila". A regra 3 do `CHAT_RULES`
  empurra para essa resposta; o contrato v2 (§3.6 receptividade, §5 interpretação) é a correção prevista
  para a S15-3. Próxima rodada mede se resolve.
- A primeira pergunta numa reunião de 2 h leva ~45 s (10,7 mil tokens lidos sem cache); as seguintes
  reaproveitam o prefixo.
- As falhas restantes são as mesmas da linha de base (S14-1 e S15-3) e a variação do modelo.
