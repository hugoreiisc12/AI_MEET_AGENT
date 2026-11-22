# Linha de base do agente — 22/11/2026

Modelo: `ModelProfile(provider='ollama', model='qwen2.5:7b', context_tokens=32768, native_tools=True, json_mode=True)` · contrato: `SPEC_CONTRACT.md`

**19/22 checagens** · p50 524 s · p95 6632 s

Prompt = tokens do prompt e tempo de leitura no Ollama. O Ollama conta também o que veio do cache;
o tempo mostra o cache: prefixo reaproveitado lê em ~1 s, sem cache leva dezenas de segundos.

| Suíte | Regra | Resultado | Tempo | Prompt |
|---|---|---|---|---|
| v1 | resumo | ok | 92 s | 9473 em 61.7 s |
| v1 | §7 decisão aprovada | ok | 6632 s | 4076 em 55.0 s |
| v1 | §4 proposta ≠ decisão | ok | 557 s | 4333 em 2.5 s |
| v1 | §7 responsável só se atribuído | ok | 10 s | 4081 em 1.0 s |
| v1 | §4/§16 não preencher lacunas | ok | 4 s | 4078 em 0.7 s |
| v1 | §7 compromisso explícito | ok | 5 s | 4079 em 0.6 s |
| v1 | §4 não presumir concordância | ok | 18 s | 4075 em 0.6 s |
| v1 | §11 avaliação crítica | ok | 7302 s | 4549 em 3.3 s |
| v2 | §14 continuidade | ok | 3670 s | 5451 em 40.7 s |
| v2 | §3.7 didática | ok | 3307 s | 5556 em 25.6 s |
| v2 | §20 citação da reunião aberta | ok | 342 s | 5109 em 19.4 s |
| v2 | §14 decisão revista depois | ok | 3650 s | 5251 em 34.4 s |
| v2 | §14 pendência resolvida depois | ok | 2095 s | 5223 em 14.8 s |
| v2 | §7 decisão condicionada | ok | 1562 s | 5275 em 2.0 s |
| v2 | §10.1 perguntas para você | falha: não casou /\?/ | 125 s | 5700 em 3.2 s |
| v2 | S14-2 search_meetings | falha: não usou search_meetings | 943 s | 5672 em 3.8 s |
| v2 | §4 não misturar reuniões | ok | 2604 s | 5359 em 1.1 s |
| v2 | S13-3 busca acha o trecho da paráfrase | ok | 6 s | - |
| v2 | §5 paráfrase em reunião de 2 h (S13-3) | ok | 4466 s | 8200 em 81.9 s |
| v2 | §3.6 pergunta ambígua: as duas leituras ou pergunta de volta | falha: não casou /\?/25[\s\S]*sexta/sexta[\s\S]*25/ | 490 s | 5538 em 36.8 s |
| v2 | S15-1 preferência gravada muda o formato | ok | 54 s | 5498 em 35.2 s |
| v2 | S14-3 pergunta repetida volta do cache | ok | 0 s | - |

## Leitura (2026-11-22, contrato v2 ligado, MEMORY_V2=true)

- **19/22** contra 13/16 da linha de base (com 6 casos novos mais difíceis). Passaram a funcionar: pendência
  resolvida em outra reunião (S14-1), "Perguntas para você" (§10.1), paráfrase na reunião de 2 h (regra 3
  do chat: procurar sinônimos antes de dizer "não foi mencionado"), preferência gravada mudando o formato
  (S15-1) e pergunta repetida vinda do cache (S14-3).
- **Contrato compacto no chat:** o prompt caiu de ~7,6 mil para ~4 mil tokens.
- **Falhas que ficam:** o modelo piso não chama `search_meetings` (prefere responder com o que já veio no
  contexto, que costuma bastar); "E o prazo?" ambíguo é respondido com uma leitura só, sem perguntar de volta;
  "o que ficou em aberto" variou entre rodadas.
- **Verificação de origem (§20):** pegou o modelo trocando a reunião de uma fala; corrigido um falso positivo
  (reunião aberta citada pelo título).
- **Tempos desta rodada não valem:** o Mac estava na bateria e dormiu durante a avaliação (log de energia).
  Medição com `caffeinate` na ADR-022 (S16-2).
