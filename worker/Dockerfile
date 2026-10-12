FROM node:20-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends adb ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY package.json package-lock.json tsconfig.json ./
RUN npm ci
COPY src ./src
RUN npx tsc -p . && npm prune --omit=dev
ENV MIDSCENE_WORKER_HOST=0.0.0.0 MIDSCENE_WORKER_PORT=18790 MIDSCENE_WORKER_REPORT_DIR=/reports
EXPOSE 18790
CMD ["node", "dist/server.js"]
