# Cycle Routes web app.
#   docker build -t cycleroutes .
#   docker run --rm -v "$PWD/data_cache:/app/data_cache" cycleroutes build     # first time (5-30 min)
#   docker run --rm -v "$PWD/data_cache:/app/data_cache" cycleroutes sources
#   docker run --rm -v "$PWD/data_cache:/app/data_cache" cycleroutes catalog
#   docker run --rm -p 8000:8000 -v "$PWD/data_cache:/app/data_cache" cycleroutes
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends openssl && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY cycleroutes ./cycleroutes
COPY web ./web
RUN pip install --no-cache-dir ".[gps]"

VOLUME /app/data_cache
EXPOSE 8000
ENTRYPOINT ["cycleroutes"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
