# Imagem única para api e workers; o comando de cada serviço vem do compose. A interface fica em frontend/Dockerfile.
# O bot não roda aqui: ele usa o Chromium do host, onde está o login do Google (ADR-006).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p data/meetings data/audio

EXPOSE 8000

CMD ["python", "main.py", "--api"]
