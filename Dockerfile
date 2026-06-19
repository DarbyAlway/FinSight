# syntax=docker/dockerfile:1

# ---- Stage 1: build the React frontend ----
FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY webapp/frontend/package.json webapp/frontend/package-lock.json ./
RUN npm ci
COPY webapp/frontend/ ./
RUN npm run build          # Vite outputs to ./dist

# ---- Stage 2: python runtime ----
FROM python:3.11-slim AS app
WORKDIR /app

# Build tools + libgomp for torch/onnxruntime wheels; curl for healthchecks; git for any VCS installs
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential git curl libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App source (respects .dockerignore; excludes node_modules, .git, caches, claude/, docs/)
COPY . .

# Built frontend from stage 1 -> exactly where mount_frontend() serves it
COPY --from=frontend /app/frontend/dist ./webapp/frontend/dist

# Model/data caches live under /root/.cache, mounted as a persistent volume in compose
ENV HF_HOME=/root/.cache/huggingface \
    FASTEMBED_CACHE_PATH=/root/.cache/fastembed

EXPOSE 8000
CMD ["uvicorn", "webapp.app:app", "--host", "0.0.0.0", "--port", "8000"]
