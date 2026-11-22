"""Indexa para a memória do agente (ADR-022) as reuniões gravadas antes dela, ou depois de trocar
o modelo de embeddings (EMBEDDING_MODEL). Idempotente: trecho já indexado e sem mudança é pulado.
Roda sozinho a cada `docker compose up` (serviço memory-index).

    python -m scripts.reindex_memory
"""
import sys
import time


def main() -> int:
    from config.settings import get_settings
    if not get_settings().memory_v2:
        print("MEMORY_V2=false: memória do agente desligada, nada a indexar.")
        return 0
    from presentation.container import get_container
    c = get_container()
    meetings = [m for m in c.repository.list_all() if m.is_transcribed]
    t0 = time.time()
    for n, meeting in enumerate(meetings, 1):
        c.indexer.index(meeting)
        print(f"[{n}/{len(meetings)}] {meeting.id} {meeting.title}")
    print(f"{len(meetings)} reuniões indexadas em {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
