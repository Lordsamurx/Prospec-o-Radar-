# Imagem da v3. Sem segredos: o .env entra só em tempo de execução.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 RADAR_NO_PARENT_ENV=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY backend ./backend
COPY templates-site ./templates-site
COPY scripts ./scripts

RUN useradd --create-home appuser && mkdir -p /app/data/previews && chown -R appuser /app/data \
    && sed -i 's/\r$//' scripts/docker-entrypoint.sh && chmod +x scripts/docker-entrypoint.sh

ENV PYTHONPATH=/app/backend
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"
ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]
CMD ["sh", "-c", "python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-8000}"]
