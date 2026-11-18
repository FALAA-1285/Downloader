FROM python:3.13-slim

# FFmpeg dipakai (ffprobe) untuk memvalidasi file video/audio hasil unduhan.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Install Chromium dan pustaka sistem untuk fitur Playwright dynamic rendering & sniffer
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
RUN /opt/venv/bin/playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /app/storage/downloads /app/storage/temp \
    && chown -R app:app /app/storage \
    && chown -R app:app /opt/playwright
USER app

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
