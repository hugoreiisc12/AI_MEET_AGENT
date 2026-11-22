"""Avaliação do agente contra o contrato (SPEC_CONTRACT.md) — S8-2, ADR-014.

    python -m scripts.eval_agent            # agente configurado no container.py
    python -m scripts.eval_agent --show     # imprime também as respostas
    python -m scripts.eval_agent --save docs/eval/linha-de-base.md   # grava o resultado (S12-4)

Usa o LLM de verdade (o do .env): leva alguns minutos com o Ollama local.
Uma reunião sintética curta tem, de propósito, uma decisão aprovada, uma proposta
adiada, uma tarefa com dono, uma tarefa sem dono e uma divergência. Cada pergunta
testa uma regra do contrato. As checagens são por palavra-chave: servem para
comparar versões do agente, não como prova; leia as respostas com --show.

v2 (ADR-022, S12-4): três reuniões ligadas (mesmas pessoas, a data da integração muda na
segunda, a migração volta na terceira), num repositório temporário. Testa continuidade entre
reuniões, citação, didática e pergunta em aberto. Mede o tempo e, no Ollama, quanto levou a leitura
do prompt (com o prefixo em cache ela cai para ~1 s: é a medida do S12-5).
"""
from __future__ import annotations

import argparse
import re
import statistics
import sys
import tempfile
import time
from datetime import date, datetime

from domain.entities.meeting import Decision, Meeting, Summary, Task

TRANSCRIPT = """[00:00] Ana: Bom dia. O objetivo de hoje é decidir como integrar o sistema de pedidos com o financeiro.
[00:20] Bruno: Eu proponho usar uma fila de mensagens entre os dois sistemas, mas preciso validar com a infraestrutura.
[00:45] Carla: O financeiro fecha o mês no dia 25, então qualquer mudança precisa estar pronta antes disso.
[01:10] Ana: Então está decidido: a integração entra em produção antes do dia 25.
[01:20] Bruno: Concordo.
[01:45] Bruno: Sobre migrar o banco de dados para a nuvem, acho que vale a pena estudar, mas não precisa ser agora.
[02:05] Ana: Vamos deixar a migração para a nuvem para discutir em outra reunião.
[02:20] Ana: Carla, você fica responsável por enviar o calendário de fechamento até sexta-feira.
[02:30] Carla: Combinado, envio até sexta.
[02:45] Bruno: Alguém precisa revisar os contratos com o fornecedor da fila.
[03:00] Ana: Ainda não sabemos quem vai fazer isso.
[03:10] Carla: Eu discordo de colocar a integração antes do fechamento, é arriscado mexer perto do dia 25.
[03:25] Ana: Entendo, mas a decisão está mantida."""

PARTICIPANTS = ["Ana", "Bruno", "Carla"]
NAMES = "|".join(PARTICIPANTS)
NOT_FOUND = ["não foi mencionad", "não há ", "não houve", "não consta", "não foi discutid", "não foi informad",
             "não foi definid", "não existem elementos", "não foi citad", "não foi abordad", "não identifiquei",
             "não foi estabelecid", "não há informaç", "não foram mencionad", "não foi apresentad"]

# (pergunta, regra do contrato, checagens)
#   any: ao menos um termo · all: todos · none: nenhum regex pode casar
QUESTIONS = [
    ("Quais decisões foram aprovadas na reunião?", "§7 decisão aprovada",
     {"all": ["25"], "none": [r"nuvem[^.\n]{0,60}\b(foi aprovad|aprovad[oa]\b)",  # nuvem como aprovada
                              r"\b(duas|três|2|3)\s+decis", r"\n\s*\d+\.[^\n]*nuvem"]}),
    ("A migração do banco de dados para a nuvem foi aprovada?", "§4 proposta ≠ decisão",
     {"any": ["não foi aprovad", "não foi decidid", "adiad", "outra reunião", "não houve aprovação", "proposta",
              "não chegou a ser aprovad", "não foi tomada"],
      "none": [r"^\s*sim\b", r"(?<!não )\bfoi aprovada\b"]}),
    ("Quem ficou responsável por revisar os contratos com o fornecedor da fila?", "§7 responsável só se atribuído",
     {"any": NOT_FOUND + ["ninguém", "não sabemos", "não se sabe", "não definiu", "indefinid", "não foi atribuíd",
                          "ainda não", "sem responsável"],
      "none": [rf"\b({NAMES})\s+(ficou|é|será|está|foi)\s+(o |a )?respons"]}),
    ("Qual foi o orçamento aprovado para a integração?", "§4/§16 não preencher lacunas",
     {"any": NOT_FOUND + ["não foi aprovado nenhum orçamento", "nenhum orçamento", "não se falou", "não trata"],
      "none": [r"R\$\s*\d"]}),
    ("Quem ficou responsável pelo calendário de fechamento e até quando?", "§7 compromisso explícito",
     {"all": ["Carla", "sexta"]}),
    ("Todos concordaram com a data da integração?", "§4 não presumir concordância",
     {"all": ["Carla"], "any": ["discord", "arrisc", "não"]}),
    ("O que você achou da reunião?", "§11 avaliação crítica",
     {"any": ["risco", "arrisc", "pendente", "não ficou", "esclarec", "melhorar", "lacuna", "indefinid"],
      "min_chars": 300}),
]

TRANSCRIPT_2 = """[00:00] Ana: Retomando a integração com o financeiro. Bruno, a infraestrutura validou a fila?
[00:15] Bruno: Validou. A fila de mensagens está liberada.
[00:40] Carla: Continuo preocupada com o fechamento do dia 25. Se a integração falhar, o financeiro fecha o mês com dados errados.
[01:05] Ana: Faz sentido. Então mudamos: a integração entra em produção no dia 28, depois do fechamento.
[01:15] Bruno: Concordo com o dia 28.
[01:20] Carla: Concordo.
[01:40] Ana: Bruno, você fica com a revisão dos contratos do fornecedor da fila, até o dia 20.
[01:50] Bruno: Fechado."""

TRANSCRIPT_3 = """[00:00] Ana: Hoje voltamos ao assunto da migração do banco de dados para a nuvem.
[00:20] Bruno: Fiz uma estimativa: cerca de 50 mil reais no primeiro ano.
[00:45] Ana: A migração está aprovada, desde que o financeiro confirme que o orçamento cabe.
[01:00] Carla: Eu consulto o financeiro e trago a resposta.
[01:20] Bruno: Ainda falta definir quem vai liderar a migração.
[01:30] Ana: Isso fica para depois."""

# Resumos fixos: a v2 mede o chat entre reuniões, não o resumo (a v1 já mede).
LINKED = [
    ("m1", "Integração pedidos x financeiro", datetime(2026, 11, 3, 10), TRANSCRIPT, Summary(
        overview="Integração entre pedidos e financeiro.", topics=["integração", "migração para a nuvem"],
        decisions=[Decision("A integração entra em produção antes do dia 25", status="aprovada"),
                   Decision("Migrar o banco de dados para a nuvem", status="proposta")],
        tasks=[Task("Enviar o calendário de fechamento", "Carla", "sexta-feira"),
               Task("Revisar os contratos com o fornecedor da fila")])),
    ("m2", "Acompanhamento da integração", datetime(2026, 11, 10, 10), TRANSCRIPT_2, Summary(
        overview="A data da integração foi revista por causa do fechamento.", topics=["integração"],
        decisions=[Decision("A integração entra em produção no dia 28, depois do fechamento", status="aprovada")],
        tasks=[Task("Revisar os contratos com o fornecedor da fila", "Bruno", "dia 20")])),
    ("m3", "Migração para a nuvem", datetime(2026, 11, 17, 10), TRANSCRIPT_3, Summary(
        overview="Migração do banco para a nuvem.", topics=["migração para a nuvem", "orçamento"],
        decisions=[Decision("Migrar o banco de dados para a nuvem, se o orçamento couber", status="condicionada")],
        tasks=[Task("Consultar o financeiro sobre o orçamento da migração", "Carla"),
               Task("Definir quem vai liderar a migração")])),
]

# (reunião aberta, pergunta, regra do contrato, checagens) · match: todo regex precisa casar
LINKED_QUESTIONS = [
    ("m2", "A data de entrada em produção da integração mudou em relação à reunião anterior?", "§14 continuidade",
     {"all": ["25", "28"], "any": ["Integração pedidos", "03/11", "anterior"]}),
    ("m2", "Por que a data mudou? Explique para quem não participou.", "§3.7 didática",
     {"all": ["Carla", "fechamento"], "min_chars": 250}),
    ("m2", "Mostre a fala em que a nova data foi decidida.", "§20 citação da reunião aberta",
     {"match": [r"\[01:05\]\W*Ana"]}),
    ("m1", "A decisão sobre a data da integração continua valendo?", "§14 decisão revista depois",
     {"all": ["28"], "any": ["Acompanhamento", "10/11", "posterior", "revist"]}),
    ("m1", "Quem vai revisar os contratos com o fornecedor da fila?", "§14 pendência resolvida depois",
     {"all": ["Bruno"], "any": ["Acompanhamento", "10/11", "posterior"]}),
    ("m3", "A migração para a nuvem foi aprovada?", "§7 decisão condicionada",
     {"all": ["orçamento"], "any": ["condicion", "desde que"]}),
    ("m3", "O que ficou em aberto nesta reunião?", "§10.1 perguntas para você",
     {"any": ["liderar", "lidera"], "match": [r"\?"]}),
    ("m3", "Procure nas minhas outras reuniões o que o Bruno disse sobre a validação da infraestrutura.",
     "S14-2 search_meetings", {"any": ["valid", "liberad"], "searched": True}),
    ("m3", "Qual foi o orçamento da integração com o financeiro?", "§4 não misturar reuniões",
     {"any": NOT_FOUND + ["não foi definido", "não tenho"], "none": [r"R\$\s*\d", r"50 mil[^.\n]{0,60}integra"]}),
]

def long_transcript() -> tuple[str, str]:
    """Reunião de ~2 h (~1.100 falas, ~90 mil caracteres) com um fato só, dito com outras palavras
    do que as da pergunta: mede a busca nos trechos (S13-3)."""
    subjects = ["o cronograma do aplicativo", "a pesquisa com clientes", "o treinamento do suporte",
                "a campanha de marketing", "o painel de vendas", "a contratação do time", "a auditoria interna",
                "o novo escritório", "a política de férias", "o portal do parceiro", "a pauta do conselho"]
    verbs = ["atualizou", "comentou", "revisou", "apresentou", "questionou", "detalhou", "resumiu"]
    names = ["Ana", "Bruno", "Carla", "Diego"]
    lines = []
    for i in range(1100):
        t = i * 6.5
        lines.append(f"[{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{int(t % 60):02d}] {names[i % 4]}: "
                     f"{names[(i + 1) % 4]} {verbs[i % 7]} {subjects[(i * 3) % 11]}, item {i}, sem mudança no plano.")
    lines[640] = "[01:09:20] Carla: O fornecedor da fila cobra 12 mil reais por mês, com reajuste anual."
    return "\n".join(lines), "Quanto custa por mês o serviço de mensageria?"


from use_cases.contract_checks import FALLBACK, contradicts_itself, is_portuguese


def check(answer: str, rules: dict) -> list[str]:
    """Regras violadas pela resposta (vazio = passou)."""
    low = answer.lower()
    fails = []
    if not is_portuguese(answer):
        fails.append("não está em português")
    if contradicts_itself(answer):
        fails.append("diz que não foi mencionado e responde mesmo assim")
    if "all" in rules and not all(t.lower() in low for t in rules["all"]):
        fails.append(f"faltou um de {rules['all']}")
    if "any" in rules and not any(t.lower() in low for t in rules["any"]):
        fails.append("faltou o termo esperado")
    for pattern in rules.get("none", []):
        if re.search(pattern, answer, re.IGNORECASE | re.MULTILINE):
            fails.append(f"casou o proibido /{pattern}/")
    for pattern in rules.get("match", []):
        if not re.search(pattern, answer, re.IGNORECASE | re.MULTILINE):
            fails.append(f"não casou /{pattern}/")
    if len(answer) < rules.get("min_chars", 0):
        fails.append(f"curta demais ({len(answer)} caracteres)")
    return fails


def check_summary(summary) -> list[str]:
    fails = []
    for d in summary.decisions:
        if "nuvem" in d.description.lower():
            status = getattr(d, "status", "")
            if status == "aprovada" or (not status and not re.search(r"adiad|outra reunião|discutir|propost",
                                                                     d.description + d.context, re.I)):
                fails.append(f"proposta registrada como decisão aprovada: {d.description!r}")
    for t in summary.tasks:
        if "contrat" in t.description.lower() and t.responsible in PARTICIPANTS:
            fails.append(f"tarefa sem dono atribuída a {t.responsible}")
    if not any(t.responsible == "Carla" and "calend" in t.description.lower() for t in summary.tasks):
        fails.append("faltou a tarefa da Carla (calendário de fechamento)")
    return fails


def _tokens_read(llm) -> str:
    """Tokens do prompt e o tempo que o Ollama levou para lê-los. O Ollama conta também os tokens
    que vieram do cache; o tempo é que mostra o cache (prefixo em cache: ~1 s; sem ele: dezenas)."""
    usage = getattr(getattr(llm, "_model", None), "last_usage", None) or {}
    if not usage.get("prompt_eval_count"):
        return ""
    return f"{usage['prompt_eval_count']} em {(usage.get('prompt_eval_duration') or 0) / 1e9:.1f} s"


def _ask(uc, meeting, question, rules, llm):
    from use_cases.chat_with_meeting import ChatWithMeetingInput
    t0 = time.time()
    r = uc.execute(ChatWithMeetingInput(meeting=meeting, question=question, history=[]))
    took = time.time() - t0
    fails = [r.error_message] if not r.success else check(r.answer, rules)
    if rules.get("searched") and not r.searched:
        fails.append("não usou search_meetings")
    return r.answer, fails, took, _tokens_read(llm)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--show", action="store_true", help="imprime as respostas")
    parser.add_argument("--save", help="grava o resultado em Markdown (linha de base)")
    args = parser.parse_args()

    from config.settings import get_settings
    from infrastructure.embeddings import build_embedder
    from infrastructure.index_store import IndexStore
    from infrastructure.json_meeting_repository import JsonMeetingRepository
    from use_cases.meeting_index import MemoryIndexer
    from infrastructure.memory_store import JsonMemoryStore
    from presentation.container import get_container
    from use_cases.chat_with_meeting import ChatWithMeetingInput, ChatWithMeetingUC
    from use_cases.summarize_meeting import SummarizeMeetingInput

    c = get_container()
    llm = c.chat_with_meeting._llm
    profile = getattr(getattr(llm, "_model", None), "profile", None)
    print(f"Agente: {type(llm).__name__} · {profile}\n")
    rows = []  # (suíte, regra, falhas, segundos, tokens lidos)

    def report(suite, rule, fails, took, tokens, question="", answer=""):
        rows.append((suite, rule, fails, took, tokens))
        print(f"{'OK   ' if not fails else 'FALHA'} {suite} {rule} ({took:.0f}s, prompt {tokens or '-'}) {'; '.join(fails)}")
        if args.show and answer:
            print("   P:", question, "\n   R:", answer.replace("\n", "\n      "), "\n")

    meeting = Meeting(id="eval", title="Integração pedidos x financeiro", transcript_text=TRANSCRIPT,
                      transcript_formatted=TRANSCRIPT, participants=PARTICIPANTS)
    t0 = time.time()
    s = c.summarize_meeting.execute(SummarizeMeetingInput(meeting=meeting))
    fails = [s.error_message] if not s.success else check_summary(s.summary)
    meeting.summary = s.summary if s.success else None  # como em produção: o chat vem depois do resumo
    report("v1", "resumo", fails, time.time() - t0, _tokens_read(llm))
    if args.show and s.success:
        print("   decisões:", [(d.description, getattr(d, 'status', '')) for d in s.summary.decisions])
        print("   tarefas:", [(t.description, t.responsible) for t in s.summary.tasks])
    for question, rule, rules in QUESTIONS:
        answer, fails, took, tokens = _ask(c.chat_with_meeting, meeting, question, rules, llm)
        report("v1", rule, fails, took, tokens, question, answer)

    with tempfile.TemporaryDirectory() as tmp:  # nunca o repositório de verdade
        repo = JsonMeetingRepository(f"{tmp}/meetings")  # notas fora da pasta das reuniões, como em produção
        indexer = MemoryIndexer(IndexStore(f"{tmp}/index"), build_embedder(get_settings()))
        from infrastructure.hot_cache import ProcessCache
        from use_cases.agent_cache import AgentCache
        cache = AgentCache(ProcessCache())
        uc = ChatWithMeetingUC(llm, repository=repo, max_context_chars=c.chat_with_meeting._max_chars,
                               memory_store=JsonMemoryStore(f"{tmp}/memories.json"), indexer=indexer,
                               agent_cache=cache)
        for mid, title, started, text, summary in LINKED:
            repo.save(Meeting(id=mid, owner_id="eval", title=title, started_at=started, transcript_text=text,
                              transcript_formatted=text, participants=PARTICIPANTS, summary=summary))
        for mid, question, rule, rules in LINKED_QUESTIONS:
            answer, fails, took, tokens = _ask(uc, repo.find_by_id(mid), question, rules, llm)
            report("v2", rule, fails, took, tokens, question, answer)
        text, question = long_transcript()
        long = Meeting(id="m4", owner_id="eval", title="Status geral", started_at=datetime(2026, 11, 18, 9),
                       transcript_text=text, transcript_formatted=text, participants=["Ana", "Bruno", "Carla", "Diego"],
                       summary=Summary(overview="Atualizações de status de vários projetos.", topics=["status"]))
        repo.save(long)
        t0 = time.time()
        found = "12 mil" in uc._context(long, question)[1]  # a busca, separada do que o modelo faz com ela
        report("v2", "S13-3 busca acha o trecho da paráfrase", [] if found else ["trecho fora do contexto"],
               time.time() - t0, "")
        answer, fails, took, tokens = _ask(uc, long, question, {"all": ["12 mil"]}, llm)
        report("v2", "§5 paráfrase em reunião de 2 h (S13-3)", fails, took, tokens, question, answer)
        answer, fails, took, tokens = _ask(uc, repo.find_by_id("m1"), "E o prazo?",
                                           {"match": [r"\?|25[\s\S]*sexta|sexta[\s\S]*25"]}, llm)
        report("v2", "§3.6 pergunta ambígua: as duas leituras ou pergunta de volta", fails, took, tokens, "E o prazo?", answer)
        from use_cases.meeting_memory import new_note
        uc._memory.add(new_note("eval", "Prefiro respostas em tópicos curtos, no máximo três itens."))
        answer, fails, took, tokens = _ask(uc, repo.find_by_id("m2"), "Quais foram as decisões desta reunião?",
                                           {"match": [r"^\s*(?:[-•*]|\d+[.)])\s"]}, llm)
        report("v2", "S15-1 preferência gravada muda o formato", fails, took, tokens, "Quais foram as decisões?", answer)
        t0 = time.time()  # CAG (S14-3): a mesma pergunta de novo não vai ao modelo
        asked = "Quem participou desta reunião?"
        first = uc.execute(ChatWithMeetingInput(meeting=repo.find_by_id("m3"), question=asked, history=[]))
        t0 = time.time()
        again = uc.execute(ChatWithMeetingInput(meeting=repo.find_by_id("m3"), question=asked, history=[]))
        fails = [] if again.path == "cache" else [f"caminho {again.path}"
                                                  + (" (1ª resposta foi a padrão, que não vai ao cache)" if first.answer == FALLBACK else "")]
        report("v2", "S14-3 pergunta repetida volta do cache", fails, time.time() - t0, "")

    passed = sum(not r[2] for r in rows)
    times = sorted(r[3] for r in rows)
    p50, p95 = statistics.median(times), times[min(len(times) - 1, round(0.95 * (len(times) - 1)))]
    print(f"\n{passed}/{len(rows)} checagens passaram · p50 {p50:.0f}s · p95 {p95:.0f}s")
    if args.save:
        _save(args.save, profile, rows, passed, p50, p95)
    return 0 if passed == len(rows) else 1


def _save(path, profile, rows, passed, p50, p95) -> None:
    from pathlib import Path
    from config.settings import get_settings
    lines = [f"# Linha de base do agente — {date.today():%d/%m/%Y}", "",
             f"Modelo: `{profile}` · contrato: `{get_settings().agent_contract_path}`", "",
             f"**{passed}/{len(rows)} checagens** · p50 {p50:.0f} s · p95 {p95:.0f} s", "",
             "Prompt = tokens do prompt e tempo de leitura no Ollama. O Ollama conta também o que veio do cache;",
             "o tempo mostra o cache: prefixo reaproveitado lê em ~1 s, sem cache leva dezenas de segundos.", "",
             "| Suíte | Regra | Resultado | Tempo | Prompt |", "|---|---|---|---|---|"]
    for suite, rule, fails, took, tokens in rows:
        lines.append(f"| {suite} | {rule} | {'ok' if not fails else 'falha: ' + '; '.join(fails).replace('|', '/')} "
                     f"| {took:.0f} s | {tokens or '-'} |")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"gravado em {path}")


if __name__ == "__main__":
    sys.exit(main())
