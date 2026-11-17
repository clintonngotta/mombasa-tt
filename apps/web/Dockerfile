# Development image for the web app (used by the root compose.yml). Build context is the repository root
# because the app type-checks against the generated API types in packages/contracts.
FROM node:22-alpine

RUN npm install -g pnpm@10

WORKDIR /app/apps/web
COPY apps/web/package.json apps/web/pnpm-lock.yaml apps/web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY packages /app/packages
COPY apps/web ./

EXPOSE 5173
CMD ["pnpm", "exec", "vite", "--host", "0.0.0.0", "--port", "5173", "--strictPort"]
