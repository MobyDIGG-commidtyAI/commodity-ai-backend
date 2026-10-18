# Commodity AI API + dashboard. On Cloud Run DATA_DIR points at the shared bucket mount (deploy/gcp.sh);
# the export baked in below is the fallback when no bucket is mounted (local runs, first boot).
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src \
    DATA_DIR=/app/data/export TH_MARKUP=1.0 PORT=8080
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
COPY api ./api
COPY data/export ./data/export
EXPOSE 8080
CMD ["sh", "-c", "uvicorn api.app:app --host 0.0.0.0 --port ${PORT}"]
