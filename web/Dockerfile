# Сайт GoPoint: сборка в статику и раздача через Caddy (он же HTTPS и прокси к серверу).
FROM node:24.22.2-alpine AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY . .
RUN npm run build

FROM caddy:2.11.7-alpine
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /web/dist /srv
