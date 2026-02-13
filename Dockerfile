# Stage 1: Dependencies
FROM python:3.12-slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml .
RUN pip install --no-cache-dir --prefix=/install .

# Stage 2: Runtime
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 ffmpeg libsndfile1 && rm -rf /var/lib/apt/lists/*
RUN groupadd -r aihm && useradd -r -g aihm -d /app -s /sbin/nologin aihm

COPY --from=builder /install /usr/local
WORKDIR /app
COPY . .
RUN chown -R aihm:aihm /app

USER aihm
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
