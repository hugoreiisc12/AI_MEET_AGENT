"""Script para inserir reunião mock diretamente no MongoDB."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from infrastructure.mongodb_documents import MeetingDocument, SummaryEmbedded, TaskEmbedded, DecisionEmbedded

DATA = {
  "reuniao": {
    "id": "REUNIAO-2026-06-09-001",
    "titulo": "Reunião Geral de Alinhamento Técnico e Operacional",
    "descricao": "Reunião realizada para alinhamento técnico da equipe, discussão sobre arquitetura backend em Java, revisão de processos internos, automações, qualidade, infraestrutura e definição das próximas entregas da sprint atual.",
    "categoria": "Alinhamento Técnico",
    "status": "Finalizada",
    "prioridade": "Alta",
    "data": "2026-06-09",
    "dia_semana": "Terça-feira",
    "horario_inicio": "15:30",
    "horario_fim": "16:47",
    "duracao_total_minutos": 77,
    "plataforma": {
      "tipo": "Google Meet",
      "sala": "Sala Engenharia Backend",
      "link": "https://meet.google.com/reuniao-tecnica-backend",
      "gravacao_ativa": True,
      "chat_habilitado": True,
      "compartilhamento_tela": True
    },
    "organizador": {
      "nome": "Hugo",
      "cargo": "Líder Técnico",
      "departamento": "Tecnologia",
      "responsavel_ata": True
    },
    "objetivos_reuniao": [
      "Discutir melhorias técnicas no backend",
      "Avaliar performance das APIs",
      "Definir responsabilidades da sprint",
      "Alinhar equipe de QA e desenvolvimento",
      "Melhorar comunicação operacional",
      "Analisar arquitetura Java",
      "Planejar próximos deploys"
    ],
    "participantes": [
      {
        "id": "USER-001",
        "nome": "Elton",
        "cargo": "Desenvolvedor Backend Senior",
        "departamento": "Desenvolvimento",
        "email": "elton@empresa.com",
        "presenca_confirmada": True,
        "entrada_reuniao": "15:27",
        "saida_reuniao": "16:47",
        "tempo_total_online_minutos": 80,
        "camera_ligada": True,
        "microfone_ativo": True,
        "quantidade_interacoes": 14,
        "nivel_participacao": "Alta",
        "especialidade": [
          "Java",
          "Spring Boot",
          "Arquitetura Backend",
          "APIs REST",
          "Mensageria"
        ],
        "participacoes": [
          {
            "ordem": 1,
            "horario_inicio": "15:35",
            "horario_fim": "15:48",
            "duracao_minutos": 13,
            "tipo": "Apresentação Técnica",
            "tema": "Arquitetura Java",
            "assunto_detalhado": "Melhoria da arquitetura de microsserviços utilizando Java Spring Boot",
            "fala": "Elton iniciou uma apresentação técnica explicando problemas de escalabilidade identificados no backend atual. Demonstrou alternativas utilizando Java Spring Boot, melhorias em gerenciamento de threads, otimização de consumo de memória e estratégias para redução de latência nas APIs.",
            "palavras_chave": [
              "Java",
              "Spring Boot",
              "Performance",
              "Threads",
              "Microsserviços"
            ],
            "interacoes": [
              {
                "com": "Hugo",
                "tipo": "Pergunta",
                "conteudo": "Questionou sobre impacto na infraestrutura atual."
              },
              {
                "com": "Felipe",
                "tipo": "Discussão",
                "conteudo": "Debateu impactos nos testes automatizados."
              }
            ],
            "observacoes": [
              "Compartilhou tela",
              "Mostrou diagramas de arquitetura",
              "Apresentou benchmark interno"
            ]
          },
          {
            "ordem": 2,
            "horario_inicio": "16:04",
            "horario_fim": "16:14",
            "duracao_minutos": 10,
            "tipo": "Discussão Técnica",
            "tema": "Integração API REST",
            "assunto_detalhado": "Padronização das APIs REST e segurança",
            "fala": "Comentou sobre a necessidade de padronização dos endpoints REST, melhoria de autenticação JWT e controle de logs para rastreamento de falhas.",
            "palavras_chave": [
              "JWT",
              "REST API",
              "Segurança",
              "Logs"
            ]
          },
          {
            "ordem": 3,
            "horario_inicio": "16:31",
            "horario_fim": "16:36",
            "duracao_minutos": 5,
            "tipo": "Sugestão",
            "tema": "Mensageria",
            "fala": "Sugeriu utilização de filas RabbitMQ para desacoplamento de processos críticos."
          }
        ],
        "tarefas_recebidas": [
          {
            "id": "TASK-001",
            "titulo": "Documentar arquitetura Java",
            "descricao": "Criar documentação técnica completa sobre a nova arquitetura proposta.",
            "prazo": "2026-06-12",
            "prioridade": "Alta",
            "status": "Pendente"
          },
          {
            "id": "TASK-002",
            "titulo": "Criar POC com Spring Boot",
            "descricao": "Desenvolver prova de conceito da nova estrutura backend.",
            "prazo": "2026-06-15",
            "prioridade": "Alta",
            "status": "Em andamento"
          }
        ]
      },
      {
        "id": "USER-002",
        "nome": "Felipe",
        "cargo": "QA Engineer",
        "departamento": "Qualidade",
        "email": "felipe@empresa.com",
        "presenca_confirmada": True,
        "entrada_reuniao": "15:30",
        "saida_reuniao": "16:46",
        "tempo_total_online_minutos": 76,
        "camera_ligada": False,
        "microfone_ativo": True,
        "quantidade_interacoes": 11,
        "nivel_participacao": "Alta",
        "especialidade": [
          "QA",
          "Automação",
          "Testes E2E",
          "Cypress",
          "Performance"
        ],
        "participacoes": [
          {
            "ordem": 1,
            "horario_inicio": "15:49",
            "horario_fim": "15:59",
            "duracao_minutos": 10,
            "tipo": "Validação Técnica",
            "tema": "Testes Automatizados",
            "assunto_detalhado": "Impacto das mudanças backend nos testes automatizados",
            "fala": "Felipe explicou que mudanças estruturais no backend exigirão atualização dos testes E2E e integração contínua. Também destacou a necessidade de novos testes de carga.",
            "palavras_chave": [
              "QA",
              "E2E",
              "Carga",
              "Automação"
            ],
            "interacoes": [
              {
                "com": "Elton",
                "tipo": "Pergunta",
                "conteudo": "Questionou possíveis alterações nos endpoints."
              }
            ]
          },
          {
            "ordem": 2,
            "horario_inicio": "16:18",
            "horario_fim": "16:23",
            "duracao_minutos": 5,
            "tipo": "Sugestão",
            "tema": "Pipeline CI/CD",
            "fala": "Sugeriu implementar validações automáticas antes de deploy em produção."
          }
        ],
        "tarefas_recebidas": [
          {
            "id": "TASK-003",
            "titulo": "Atualizar testes automatizados",
            "descricao": "Adequar cenários automatizados às mudanças backend.",
            "prazo": "2026-06-13",
            "prioridade": "Alta",
            "status": "Pendente"
          }
        ]
      },
      {
        "id": "USER-003",
        "nome": "Rafael",
        "cargo": "Analista de Projetos",
        "departamento": "Operações",
        "email": "rafael@empresa.com",
        "presenca_confirmada": True,
        "entrada_reuniao": "15:31",
        "saida_reuniao": "16:40",
        "tempo_total_online_minutos": 69,
        "camera_ligada": True,
        "microfone_ativo": True,
        "quantidade_interacoes": 9,
        "nivel_participacao": "Média",
        "especialidade": [
          "Gestão",
          "Cronogramas",
          "Operações"
        ],
        "participacoes": [
          {
            "ordem": 1,
            "horario_inicio": "16:00",
            "horario_fim": "16:10",
            "duracao_minutos": 10,
            "tipo": "Planejamento",
            "tema": "Cronograma Sprint",
            "assunto_detalhado": "Atualização das entregas planejadas",
            "fala": "Rafael apresentou os prazos atuais da sprint, identificou possíveis atrasos e alinhou prioridades operacionais para os próximos dias.",
            "palavras_chave": [
              "Sprint",
              "Cronograma",
              "Planejamento"
            ]
          },
          {
            "ordem": 2,
            "horario_inicio": "16:24",
            "horario_fim": "16:28",
            "duracao_minutos": 4,
            "tipo": "Feedback",
            "tema": "Comunicação",
            "fala": "Comentou sobre necessidade de melhorar alinhamento entre QA e desenvolvimento."
          }
        ],
        "tarefas_recebidas": [
          {
            "id": "TASK-004",
            "titulo": "Atualizar cronograma operacional",
            "descricao": "Reorganizar entregas da sprint após mudanças técnicas.",
            "prazo": "2026-06-10",
            "prioridade": "Alta",
            "status": "Em andamento"
          }
        ]
      },
      {
        "id": "USER-004",
        "nome": "Hugo",
        "cargo": "Líder Técnico",
        "departamento": "Tecnologia",
        "email": "hugo@empresa.com",
        "presenca_confirmada": True,
        "entrada_reuniao": "15:25",
        "saida_reuniao": "16:47",
        "tempo_total_online_minutos": 82,
        "camera_ligada": True,
        "microfone_ativo": True,
        "quantidade_interacoes": 18,
        "nivel_participacao": "Muito Alta",
        "especialidade": [
          "Infraestrutura",
          "Cloud",
          "Backend",
          "Arquitetura"
        ],
        "participacoes": [
          {
            "ordem": 1,
            "horario_inicio": "15:30",
            "horario_fim": "15:34",
            "duracao_minutos": 4,
            "tipo": "Abertura",
            "tema": "Introdução",
            "fala": "Hugo iniciou a reunião apresentando objetivos, prioridades e principais problemas identificados no ambiente atual."
          },
          {
            "ordem": 2,
            "horario_inicio": "16:11",
            "horario_fim": "16:17",
            "duracao_minutos": 6,
            "tipo": "Discussão Técnica",
            "tema": "Infraestrutura",
            "fala": "Comentou sobre melhorias de infraestrutura cloud e necessidade de monitoramento avançado."
          },
          {
            "ordem": 3,
            "horario_inicio": "16:38",
            "horario_fim": "16:47",
            "duracao_minutos": 9,
            "tipo": "Encerramento",
            "tema": "Próximos Passos",
            "fala": "Finalizou a reunião distribuindo responsabilidades, definindo prioridades e validando entregas da próxima semana."
          }
        ],
        "tarefas_recebidas": [
          {
            "id": "TASK-005",
            "titulo": "Validar infraestrutura cloud",
            "descricao": "Analisar impacto das mudanças backend na infraestrutura atual.",
            "prazo": "2026-06-14",
            "prioridade": "Alta",
            "status": "Pendente"
          }
        ]
      }
    ],
    "decisoes_tomadas": [
      {
        "horario": "16:20",
        "decisao": "Migrar parte da arquitetura para microsserviços",
        "responsavel_aprovacao": "Hugo",
        "impacto": "Alto"
      },
      {
        "horario": "16:22",
        "decisao": "Atualizar pipeline de testes automatizados",
        "responsavel_aprovacao": "Felipe",
        "impacto": "Médio"
      },
      {
        "horario": "16:25",
        "decisao": "Criar documentação técnica da arquitetura",
        "responsavel_aprovacao": "Elton",
        "impacto": "Alto"
      }
    ],
    "metricas_reuniao": {
      "quantidade_total_participantes": 4,
      "quantidade_total_falas": 10,
      "tempo_total_discussao_tecnica_minutos": 48,
      "tempo_total_planejamento_minutos": 15,
      "tempo_total_feedbacks_minutos": 8,
      "participante_mais_ativo": "Hugo",
      "tema_mais_discutido": "Java e Arquitetura Backend"
    },
    "encerramento": {
      "finalizada_por": "Hugo",
      "horario_encerramento": "16:47",
      "mensagem_final": "Equipe alinhada para continuidade das melhorias técnicas e operacionais.",
      "proxima_reuniao_prevista": "2026-06-16 15:30"
    }
  }
}


async def main():
    client = AsyncIOMotorClient("mongodb://localhost:27017/meetagent")
    await init_beanie(database=client.meetagent, document_models=[MeetingDocument])

    r = DATA["reuniao"]

    # --- Build participants list ---
    participants = [p["nome"] for p in r["participantes"]]

    # --- Build transcript formatted ---
    transcript_lines = []
    transcript_text_parts = []
    for p in r["participantes"]:
        for fala in p.get("participacoes", []):
            start = fala.get("horario_inicio", "")
            texto = fala.get("fala", "")
            transcript_lines.append(f"[{start}] {p['nome']}: {texto}")
            transcript_text_parts.append(texto)
    transcript_formatted = "\n".join(transcript_lines)
    transcript_text = "\n".join(transcript_text_parts)

    # --- Build summary ---
    tasks = []
    for p in r["participantes"]:
        for t in p.get("tarefas_recebidas", []):
            tasks.append(TaskEmbedded(
                description=f"{t['titulo']}: {t['descricao']}",
                responsible=p["nome"],
                deadline=t["prazo"],
                done=(t["status"] == "Concluída" or t["status"] == "Em andamento"),
            ))

    decisions = []
    for d in r.get("decisoes_tomadas", []):
        decisions.append(DecisionEmbedded(
            description=f"{d['decisao']} (aprovado por: {d['responsavel_aprovacao']})",
            context=f"Decisão tomada às {d['horario']}. Impacto: {d['impacto']}.",
        ))

    summary = SummaryEmbedded(
        overview=r["descricao"],
        topics=r["objetivos_reuniao"],
        tasks=tasks,
        decisions=decisions,
    )

    # --- Parse start time ---
    try:
        started_at = datetime.strptime(f"{r['data']} {r['horario_inicio']}", "%Y-%m-%d %H:%M")
    except:
        started_at = datetime.now()

    # --- Create document ---
    doc = MeetingDocument(
        id=r["id"],
        title=r["titulo"],
        started_at=started_at,
        audio_path=None,
        transcript_text=transcript_text,
        transcript_formatted=transcript_formatted,
        summary=summary,
        participants=participants,
        duration_minutes=float(r["duracao_total_minutos"]),
    )

    # Check if already exists
    existing = await MeetingDocument.get(r["id"])
    if existing:
        print(f"[SKIP] Reuniao '{r['id']}' ja existe. Pulando...")
        return

    await doc.save()
    print(f"[OK] Reuniao '{r['titulo']}' inserida com ID: {r['id']}")

    # Verify
    saved = await MeetingDocument.get(r["id"])
    print(f"[CHECK] {saved.title} -- {len(saved.participants)} participantes")
    print(f"   Summary: {saved.summary.overview[:60]}...")
    print(f"   Tarefas: {len(saved.summary.tasks)}  Decisoes: {len(saved.summary.decisions)}")


if __name__ == "__main__":
    asyncio.run(main())
