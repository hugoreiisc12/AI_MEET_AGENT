"""Quick verification of test meeting in MongoDB using pymongo."""
from pymongo import MongoClient

c = MongoClient("mongodb://localhost:27017")
col = c["meetagent"]["meetings"]

for d in col.find().sort("started_at", -1):
    print(f"  ID: {d['id']}")
    print(f"  Titulo: {d['title']}")
    print(f'  Participantes ({len(d["participants"])}): {", ".join(d["participants"])}')
    print(f'  Duracao: {d["duration_minutes"]} min')
    s = d.get("summary") or {}
    print(f'  Summary: {"SIM" if s else "NAO"}')
    if s:
        print(f'    Overview: {s.get("overview", "")[:80]}...')
        print(f'    Tarefas: {len(s.get("tasks", []))}')
        print(f'    Decisoes: {len(s.get("decisions", []))}')
    print()

c.close()
