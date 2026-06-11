"""Insere reunião de teste no MongoDB com participantes e descrições reais."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime
from pymongo import MongoClient

MEETING_ID = "teste-gravacao-001"

SEGMENTS = [
    ("Elton Canto", "Alou, alou! Testando microfone..."),
    ("Hugo dos Reis", "Alou, alou! Tá pegando?"),
    ("Felipe Chaves", "Alou, alou! Testando, testando."),
    ("Rafael Barboza", "Alou, alou! Funcionou."),
    ("Carlos Henrique", "Alou, alou! Tô ouvindo todo mundo."),
    ("Elton Canto", "Beleza, pessoal! A gravação está funcionando. Vamos fazer uma breve apresentação de cada um para registrar."),
    ("Hugo dos Reis", "Então, eu sou o Hugo dos Reis, desenvolvedor com foco em BI aqui na JFC Agricultura. Trabalho com análise de dados, dashboards e tudo que envolve inteligência de negócio pro pessoal do agro."),
    ("Felipe Chaves", "Eu sou o Felipe Chaves, desenvolvedor na JFC. Meu foco é criação de sistemas operacionais, cadastro de produtos, notas fiscais, esse tipo de coisa. Tudo que é operacional do sistema."),
    ("Carlos Henrique", "Sou o Carlos Henrique, Administrador de Banco de Dados na JFC. Atuo fortemente com consultas SAP, automações de processos, criação de databases complexos e administração de ambientes de dados."),
    ("Rafael Barboza", "Eu sou o Rafael Barboza, analista de dados sênior. Trabalho com análises de dados, visões analíticas, e desenvolvimento de aplicações mais pavimentadas com governança de dados. Também na JFC."),
    ("Elton Canto", "E eu sou o Elton Canto, coordenador do setor de desenvolvimento NIO. Atuo como cientista de dados e organizo todos os projetos do setor. Basicamente é onde todo mundo aqui atua."),
    ("Hugo dos Reis", "Então é isso, equipe reunida, gravação testada e funcionando. Podemos encerrar."),
    ("Elton Canto", "Perfeito, reunião de teste concluída. Vamos ver o resultado dessa gravação depois."),
]

PARTICIPANTES = ["Hugo dos Reis", "Felipe Chaves", "Rafael Barboza", "Carlos Henrique", "Elton Canto"]

FORMATTED = "\n".join(f"[{i*30//60:02d}:{i*30%60:02d}] {s[0]}: {s[1]}" for i, s in enumerate(SEGMENTS))
FULL_TEXT = "\n".join(s[1] for s in SEGMENTS)
DURATION = round(len(SEGMENTS) * 0.5, 1)

DOC = {
    "_id": MEETING_ID,
    "id": MEETING_ID,
    "title": "Reunião Teste — Gravação Bot Meet",
    "started_at": datetime.now(),
    "audio_path": None,
    "transcript_text": FULL_TEXT,
    "transcript_formatted": FORMATTED,
    "transcript_raw": FULL_TEXT,
    "participants": PARTICIPANTES,
    "duration_minutes": DURATION,
    "summary": {
        "overview": "Reunião de teste de gravação do bot do Google Meet. Os participantes testaram o áudio dizendo 'alou' e em seguida cada um se apresentou brevemente, descrevendo seu papel na empresa JFC Agricultura e no setor NIO.",
        "topics": [
            "Teste de gravação do Google Meet",
            "Apresentação individual dos participantes",
            "Papéis e responsabilidades na equipe NIO",
        ],
        "tasks": [
            {
                "description": "Verificar resultado da gravação de teste",
                "responsible": "Elton Canto",
                "deadline": "2026-06-11",
                "done": False,
            },
        ],
        "decisions": [
            {
                "description": "Gravação do bot funcionando corretamente",
                "context": "Todos os participantes confirmaram que o áudio foi capturado com sucesso.",
            },
        ],
        "created_at": datetime.now(),
    },
}


def main():
    client = MongoClient("mongodb://localhost:27017")
    db = client["meetagent"]
    col = db["meetings"]

    existing = col.find_one({"_id": MEETING_ID})
    if existing:
        print(f"Reunião '{MEETING_ID}' já existe. Removendo...")
        col.delete_one({"_id": MEETING_ID})

    col.insert_one(DOC)
    print(f"[OK] Reunião inserida com ID: {MEETING_ID}")
    print(f"    Participantes ({len(PARTICIPANTES)}): {', '.join(PARTICIPANTES)}")
    print(f"    Segmentos: {len(SEGMENTS)}")
    print(f"    Duração: {DURATION} min")

    saved = col.find_one({"_id": MEETING_ID})
    print(f"\n[VERIFICACAO]")
    print(f"    Titulo: {saved['title']}")
    print(f"    Transcript: {len(saved['transcript_text'])} chars")
    print(f"    Summary: {saved['summary']['overview'][:80]}...")
    print(f"    Tarefas: {len(saved['summary']['tasks'])}")
    print(f"    Decisoes: {len(saved['summary']['decisions'])}")

    client.close()
    return saved


if __name__ == "__main__":
    try:
        main()
        print("\n✅ Reunião de teste pronta!")
    except Exception as e:
        print(f"\nErro: {e}")
        sys.exit(1)
