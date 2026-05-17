# ── Imagem base ───────────────────────────────────────────────────────────
FROM python:3.11-slim

# Evita prompts interativos durante o build
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# ── Dependências de sistema ───────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ── Diretório de trabalho ─────────────────────────────────────────────────
WORKDIR /app

# ── Dependências Python ───────────────────────────────────────────────────
COPY requirements.txt requirements-collab.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-collab.txt
# ── Código da aplicação ───────────────────────────────────────────────────
COPY . .

# ── Cria pastas de dados ──────────────────────────────────────────────────
RUN mkdir -p data/meetings data/audio

# ── Porta padrão FastAPI ──────────────────────────────────────────────────
EXPOSE 8000

# ── Healthcheck ───────────────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# ── Entrypoint ────────────────────────────────────────────────────────────
CMD ["python", "main.py", "--api"]