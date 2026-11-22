# Linha de base do agente — 21/11/2026

Modelo: `ModelProfile(provider='ollama', model='qwen2.5:7b', context_tokens=32768, native_tools=True, json_mode=True)` · contrato: `SPEC_CONTRACT.md`

**16/20 checagens** · p50 16 s · p95 40 s

Prompt = tokens do prompt e tempo de leitura no Ollama. O Ollama conta também o que veio do cache;
o tempo mostra o cache: prefixo reaproveitado lê em ~1 s, sem cache leva dezenas de segundos.

| Suíte | Regra | Resultado | Tempo | Prompt |
|---|---|---|---|---|
| v1 | resumo | ok | 26 s | 6647 em 10.1 s |
| v1 | §7 decisão aprovada | ok | 17 s | 7818 em 15.2 s |
| v1 | §4 proposta ≠ decisão | ok | 6 s | 7823 em 0.2 s |
| v1 | §7 responsável só se atribuído | ok | 2 s | 7823 em 0.2 s |
| v1 | §4/§16 não preencher lacunas | ok | 1 s | 7820 em 0.2 s |
| v1 | §7 compromisso explícito | ok | 2 s | 7821 em 0.2 s |
| v1 | §4 não presumir concordância | falha: faltou um de ['Carla']; faltou o termo esperado | 2 s | 7817 em 0.3 s |
| v1 | §11 avaliação crítica | ok | 17 s | 7815 em 0.3 s |
| v2 | §14 continuidade | ok | 26 s | 8884 em 17.9 s |
| v2 | §3.7 didática | ok | 40 s | 9497 em 0.9 s |
| v2 | §20 citação da reunião aberta | ok | 12 s | 8856 em 9.6 s |
| v2 | §14 decisão revista depois | ok | 28 s | 8968 em 21.0 s |
| v2 | §14 pendência resolvida depois | ok | 19 s | 8970 em 10.2 s |
| v2 | §7 decisão condicionada | ok | 33 s | 8774 em 27.0 s |
| v2 | §10.1 perguntas para você | falha: não casou /\?/ | 26 s | 8846 em 5.8 s |
| v2 | S14-2 search_meetings | falha: não usou search_meetings | 16 s | 8813 em 9.1 s |
| v2 | §4 não misturar reuniões | ok | 13 s | 8914 em 12.3 s |
| v2 | S13-3 busca acha o trecho da paráfrase | ok | 3 s | - |
| v2 | §5 paráfrase em reunião de 2 h (S13-3) | falha: faltou um de ['12 mil'] | 61 s | 11947 em 60.2 s |
| v2 | S14-3 pergunta repetida volta do cache | ok | 0 s | - |
