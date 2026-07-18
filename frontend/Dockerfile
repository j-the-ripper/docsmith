# Build context is the repo ROOT (see docker-compose.yml) so this image can grab
# both the frontend source and the root Caddyfile.

# ---- build the React SPA ----
FROM node:20-alpine AS build
WORKDIR /app
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# ---- serve: Caddy hosts the SPA and reverse-proxies /api -> backend ----
FROM caddy:2-alpine
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv
EXPOSE 80
