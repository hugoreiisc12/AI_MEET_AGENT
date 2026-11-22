"""Transcrição parcial: segmentos que o Whisper já reconheceu enquanto a etapa "transcribing" roda.

O Whisper local grava um segmento por linha em `<id>.partial.jsonl`, ao lado do áudio; a API lê
esse arquivo para mostrar o texto em tempo real. Só o local gera parcial (o da API devolve tudo
no fim). Falhar aqui nunca derruba a transcrição: é um canal de acompanhamento, não o resultado.

ponytail: arquivo no volume compartilhado entre worker e API; se worker e API ficarem em máquinas
sem disco comum, trocar por um campo no repositório ou por Redis.
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def partial_path(audio_path: str) -> Path:
    audio = Path(audio_path)
    return audio.parent / f"{audio.name.split('.')[0]}.partial.jsonl"


class PartialWriter:
    def __init__(self, audio_path: str) -> None:
        self._path = partial_path(audio_path)
        self._file = None
        try:
            self._file = open(self._path, "w", encoding="utf-8")
        except OSError as exc:
            logger.warning("Sem transcrição parcial (%s): %s", self._path, exc)

    def append(self, start: float, end: float, text: str) -> None:
        if self._file is None or not text:
            return
        try:
            self._file.write(json.dumps({"start": round(start, 2), "end": round(end, 2), "text": text}, ensure_ascii=False) + "\n")
            self._file.flush()
        except OSError as exc:
            logger.warning("Falha ao gravar transcrição parcial: %s", exc)
            self.close()

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None


def read_partial(audio_path: str) -> list[dict]:
    path = partial_path(audio_path)
    if not path.exists():
        return []
    segments = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                segments.append(json.loads(line))
            except json.JSONDecodeError:
                break  # última linha ainda sendo escrita
    return segments


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        audio = f"{tmp}/abc123.clean.wav"
        w = PartialWriter(f"{tmp}/abc123.webm")
        w.append(0.0, 1.5, "olá")
        w.append(1.5, 3.0, "")
        w.append(3.0, 4.2, "tudo bem")
        assert read_partial(audio) == [
            {"start": 0.0, "end": 1.5, "text": "olá"},
            {"start": 3.0, "end": 4.2, "text": "tudo bem"},
        ], read_partial(audio)
        with open(partial_path(audio), "a", encoding="utf-8") as f:
            f.write('{"start": 4.2, "te')
        assert len(read_partial(audio)) == 2
        w.close()
        assert read_partial(f"{tmp}/nada.webm") == []
    print("ok")
