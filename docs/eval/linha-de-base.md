# Linha de base do agente — 21/11/2026

Modelo: `ModelProfile(provider='ollama', model='qwen2.5:7b', context_tokens=32768, native_tools=True, json_mode=True)` · contrato: `SPEC_CONTRACT.md`

**13/16 checagens** · p50 9 s · p95 26 s

Prompt = tokens do prompt e tempo de leitura no Ollama. O Ollama conta também o que veio do cache;
o tempo mostra o cache: prefixo reaproveitado lê em ~1 s, sem cache leva dezenas de segundos.

| Suíte | Regra | Resultado | Tempo | Prompt |
|---|---|---|---|---|
| v1 | resumo | ok | 26 s | 6647 em 9.0 s |
| v1 | §7 decisão aprovada | ok | 19 s | 7618 em 17.2 s |
| v1 | §4 proposta ≠ decisão | falha: faltou o termo esperado | 16 s | 7845 em 0.9 s |
| v1 | §7 responsável só se atribuído | ok | 3 s | 7623 em 0.3 s |
| v1 | §4/§16 não preencher lacunas | ok | 1 s | 7620 em 0.3 s |
| v1 | §7 compromisso explícito | ok | 2 s | 7621 em 0.3 s |
| v1 | §4 não presumir concordância | ok | 5 s | 7617 em 0.3 s |
| v1 | §11 avaliação crítica | ok | 27 s | 7615 em 0.3 s |
| v2 | §14 continuidade | ok | 22 s | 7861 em 13.7 s |
| v2 | §3.7 didática | ok | 10 s | 7966 em 4.3 s |
| v2 | §20 citação da reunião aberta | ok | 6 s | 7855 em 3.4 s |
| v2 | §14 decisão revista depois | ok | 24 s | 8040 em 17.8 s |
| v2 | §14 pendência resolvida depois | falha: faltou um de ['Bruno']; faltou o termo esperado | 8 s | 8042 em 3.3 s |
| v2 | §7 decisão condicionada | ok | 17 s | 7751 em 13.2 s |
| v2 | §10.1 perguntas para você | falha: não casou /\?/ | 4 s | 7749 em 0.4 s |
| v2 | §4 não misturar reuniões | ok | 4 s | 7861 em 3.1 s |

## Leitura (2026-11-21, contrato v1, antes de ligar a memória v2)

- **Cache de prefixo (S12-5) funcionando:** perguntas seguidas na mesma reunião leem os ~7,6 mil tokens
  do prompt em 0,3 s; a primeira de cada reunião leva 13–18 s. Na v2, o bloco de outras reuniões vai
  junto com a pergunta, então só ele é lido de novo (3–4 s). Sem o cache, ~50 s (ADR-021).
- **Falhas que a memória v2 deve resolver:** "quem revisa os contratos" na reunião antiga não usa a
  tarefa atribuída ao Bruno na reunião seguinte (S14-1); "o que ficou em aberto" não faz a pergunta
  ao usuário do §10.1 (contrato v2, S15-3).
- **Variação do modelo piso:** "a migração foi aprovada?" passou na primeira rodada e caiu na resposta
  padrão nesta (duas violações seguidas). Comparar versões pela média de rodadas, não por uma só.
- **Defeito achado e corrigido:** numa rodada o modelo usou `remember` para "O que ficou em aberto?" e
  gravou uma nota que ninguém pediu; agora isso é violação e ele responde de novo
  (`test_remember_so_quando_o_usuario_pede`).
