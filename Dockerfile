# teslai app and worker image. Multi-arch bases (amd64, arm64).

# Build the React web app into teslai/api/web.
FROM node:22-bookworm-slim@sha256:83f487e0a63425e5b4d146fb5e5be574bcbe1b7b843d3ebafdd95eaf7767a7e5 AS web
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
RUN npm run build

FROM python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

RUN useradd --system --uid 10001 --home /app teslai

COPY pyproject.toml alembic.ini ./
COPY teslai ./teslai
COPY --from=web /src/teslai/api/web ./teslai/api/web
COPY config ./config
COPY migrations ./migrations
# Editable install keeps config/ and migrations/ at their repository paths.
RUN pip install -e . && chown -R teslai /app

USER teslai
EXPOSE 8000
CMD ["sh", "-c", "teslai db upgrade && uvicorn teslai.api.app:app --host 0.0.0.0 --port 8000"]
