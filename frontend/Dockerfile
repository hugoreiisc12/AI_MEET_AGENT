# Interface nova (React/Vite) servida por Caddy. O navegador fala só com esta origem:
# /api/* é repassado para a FastAPI (sem o prefixo), então não há CORS nem chave no front.
#   docker compose up -d --build web
FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM caddy:2-alpine
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv
EXPOSE 80
