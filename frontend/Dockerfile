FROM node:20-slim AS builder
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY . .
# Baked in at build time -- Next.js inlines NEXT_PUBLIC_* vars into the
# client bundle, so this must be passed as a Docker build-arg, not a
# runtime env var. Set it to the deployed dashboard-api Cloud Run URL.
ARG NEXT_PUBLIC_API_BASE_URL=""
ARG NEXT_PUBLIC_LOOKER_EMBED_URL=""
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_LOOKER_EMBED_URL=$NEXT_PUBLIC_LOOKER_EMBED_URL
RUN npm run build

FROM node:20-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=8080
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
EXPOSE 8080
CMD ["node", "server.js"]
