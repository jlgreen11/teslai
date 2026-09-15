# teslai app and worker image. Multi-arch base (amd64, arm64).
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

RUN useradd --system --uid 10001 --home /app teslai

COPY pyproject.toml alembic.ini ./
COPY teslai ./teslai
COPY config ./config
COPY migrations ./migrations
# Editable install keeps config/ and migrations/ at their repository paths.
RUN pip install -e . && chown -R teslai /app

USER teslai
EXPOSE 8000
CMD ["sh", "-c", "teslai db upgrade && uvicorn teslai.api.app:app --host 0.0.0.0 --port 8000"]
