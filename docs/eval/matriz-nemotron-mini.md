# Linha de base do agente — 22/11/2026

Modelo: `ModelProfile(provider='ollama', model='nemotron-mini', context_tokens=16384, native_tools=False, json_mode=True)` · contrato: `SPEC_CONTRACT.md`

**3/22 checagens** · p50 13 s · p95 41 s

Prompt = tokens do prompt e tempo de leitura no Ollama. O Ollama conta também o que veio do cache;
o tempo mostra o cache: prefixo reaproveitado lê em ~1 s, sem cache leva dezenas de segundos.

| Suíte | Regra | Resultado | Tempo | Prompt |
|---|---|---|---|---|
| v1 | resumo | ok | 30 s | 4096 em 10.6 s |
| v1 | §7 decisão aprovada | falha: faltou um de ['25'] | 11 s | - |
| v1 | §4 proposta ≠ decisão | falha: faltou o termo esperado | 1 s | 3601 em 0.1 s |
| v1 | §7 responsável só se atribuído | falha: faltou o termo esperado | 1 s | 3601 em 0.1 s |
| v1 | §4/§16 não preencher lacunas | falha: faltou o termo esperado | 1 s | 3597 em 0.1 s |
| v1 | §7 compromisso explícito | falha: faltou um de ['Carla', 'sexta'] | 1 s | 3599 em 0.1 s |
| v1 | §4 não presumir concordância | falha: faltou um de ['Carla']; faltou o termo esperado | 0 s | 3597 em 0.1 s |
| v1 | §11 avaliação crítica | falha: curta demais (280 caracteres) | 3 s | 3608 em 0.2 s |
| v2 | §14 continuidade | falha: faltou um de ['25', '28']; faltou o termo esperado | 27 s | 4096 em 11.4 s |
| v2 | §3.7 didática | falha: faltou um de ['Carla', 'fechamento']; curta demais (151 caracteres) | 26 s | 4096 em 11.5 s |
| v2 | §20 citação da reunião aberta | falha: não casou /\[01:05\]\W*Ana/ | 13 s | 4096 em 11.6 s |
| v2 | §14 decisão revista depois | falha: faltou um de ['28']; faltou o termo esperado | 12 s | 4096 em 11.7 s |
| v2 | §14 pendência resolvida depois | falha: faltou o termo esperado | 14 s | 4096 em 13.5 s |
| v2 | §7 decisão condicionada | falha: faltou um de ['orçamento']; faltou o termo esperado | 13 s | 4096 em 12.7 s |
| v2 | §10.1 perguntas para você | falha: faltou o termo esperado; não casou /\?/ | 22 s | 4096 em 13.1 s |
| v2 | S14-2 search_meetings | falha: faltou o termo esperado; não usou search_meetings | 41 s | 4096 em 16.8 s |
| v2 | §4 não misturar reuniões | falha: faltou o termo esperado | 17 s | 4096 em 16.2 s |
| v2 | S13-3 busca acha o trecho da paráfrase | ok | 4 s | - |
| v2 | §5 paráfrase em reunião de 2 h (S13-3) | falha: faltou um de ['12 mil'] | 37 s | 4096 em 18.5 s |
| v2 | §3.6 pergunta ambígua: as duas leituras ou pergunta de volta | falha: não casou /\?/25[\s\S]*sexta/sexta[\s\S]*25/ | 18 s | 4096 em 17.4 s |
| v2 | S15-1 preferência gravada muda o formato | falha: não casou /^\s*(?:[-•*]/\d+[.)])\s/ | 42 s | 4096 em 17.8 s |
| v2 | S14-3 pergunta repetida volta do cache | ok | 0 s | - |

## Leitura (2026-11-22, S16-1)

Mesmo harness, mudando só o `.env` (`OLLAMA_MODEL=nemotron-mini`, `LLM_NATIVE_TOOLS=false`,
`OLLAMA_NUM_CTX_MAX=16384`): rodou sem erro e sem mudança de código, com as ferramentas por JSON. A nota
(3/22) é do modelo, não do harness: o Ollama corta o prompt em **4.096 tokens** ("prompt 4096" em todas as
linhas), a janela real do `nemotron-mini`, e nem o contrato compacto com as regras cabe nela. Confirma o piso
da ADR-022: janela de 32k e modelo do porte do `qwen2.5:7b`. Para um modelo de janela pequena, declarar a
janela real em `LLM_CONTEXT_TOKENS` faz o harness encolher os blocos em vez de deixar o Ollama cortar.

| Modelo | Janela | Ferramentas | Nota | Observação |
|---|---|---|---|---|
| `qwen2.5:7b` (piso) | 32k | nativas | **19/22** | `docs/eval/sprint-15.md` |
| `nemotron-mini` (abaixo do piso) | 4k real | JSON | 3/22 | prompt cortado em 4.096 |
| Local maior (ex.: `qwen2.5:14b`) | — | — | não medido | ~9 GB; sem espaço em disco |
| Por API (OpenAI/OpenRouter) | — | — | não medido | sem chave no `.env` |
