# syntax=docker/dockerfile:1.7
FROM node:22-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-slim AS builder
WORKDIR /app
ENV NEXT_PUBLIC_GOOGLE_AUTH_ENABLED=false
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-slim AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_PUBLIC_GOOGLE_AUTH_ENABLED=false \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000

# node:22-slim already provides the unprivileged `node` user (uid 1000).
# Keep dependency files in their own layer so ordinary UI/page changes can
# reuse the large runtime dependency layer from GHCR instead of downloading it
# again with every frontend build.
COPY --from=builder --chown=node:node /app/.next/standalone/node_modules ./node_modules
COPY --from=builder --chown=node:node /app/.next/standalone/package.json ./package.json
COPY --from=builder --chown=node:node /app/.next/standalone/server.js ./server.js
COPY --from=builder --chown=node:node /app/.next/standalone/.next ./.next
COPY --from=builder --chown=node:node /app/.next/static ./.next/static
COPY --from=builder --chown=node:node /app/public ./public

USER node
EXPOSE 3000
CMD ["node", "server.js"]
