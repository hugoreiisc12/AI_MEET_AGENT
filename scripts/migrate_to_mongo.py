"""
Migrates existing meetings from JSON files or SQLite to MongoDB.

Usage:
    python scripts/migrate_to_mongo.py          # migra do repositório ativo
    python scripts/migrate_to_mongo.py --from json   # força origem JSON
    python scripts/migrate_to_mongo.py --from sqlite  # força origem SQLite
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import argparse
from pathlib import Path
from config.settings import get_settings
from infrastructure.mongo_setup import init_mongo
from infrastructure.mongo_meeting_repository import MongoMeetingRepository


def load_json_meetings(settings):
    from infrastructure.json_meeting_repository import JsonMeetingRepository
    repo = JsonMeetingRepository(storage_path=settings.storage_path)
    return repo.list_all()


def load_sqlite_meetings(settings):
    from infrastructure.sqlite_meeting_repository import SqliteMeetingRepository
    repo = SqliteMeetingRepository(settings.repository_path)
    return repo.list_all()


def migrate():
    parser = argparse.ArgumentParser(description="Migrar reuniões para MongoDB")
    parser.add_argument("--from", dest="source", choices=["json", "sqlite"],
                        help="Forçar origem (padrão: detecta do settings)")
    args = parser.parse_args()

    settings = get_settings()

    if args.source == "json":
        meetings = load_json_meetings(settings)
        print(f"Carregadas {len(meetings)} reuniões do JSON")
    elif args.source == "sqlite":
        meetings = load_sqlite_meetings(settings)
        print(f"Carregadas {len(meetings)} reuniões do SQLite")
    else:
        meetings = []
        try:
            meetings = load_json_meetings(settings)
            print(f"Carregadas {len(meetings)} reuniões do JSON")
        except Exception:
            try:
                meetings = load_sqlite_meetings(settings)
                print(f"Carregadas {len(meetings)} reuniões do SQLite")
            except Exception as e:
                print(f"Erro ao carregar reuniões: {e}")
                sys.exit(1)

    if not meetings:
        print("Nenhuma reunião para migrar.")
        return

    print(f"Inicializando MongoDB em {settings.mongo_uri}/{settings.mongo_db_name}...")
    init_mongo(settings.mongo_uri, settings.mongo_db_name)

    mongo_repo = MongoMeetingRepository()

    success = 0
    for m in meetings:
        try:
            mongo_repo.save(m)
            success += 1
            print(f"  ✅ {m.id[:8]} — {m.title}")
        except Exception as e:
            print(f"  ❌ {m.id[:8]} — {e}")

    print(f"\nMigração concluída: {success}/{len(meetings)} reuniões salvas no MongoDB.")


if __name__ == "__main__":
    migrate()
