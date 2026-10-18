# Commodity AI API + dashboard. Ships no data: on Cloud Run DATA_DIR is the shared bucket mount that
# commodity-ai-caller keeps current (deploy/gcp.sh). Without it /api/health answers 503.
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src \
    DATA_DIR=/mnt/tank/export TH_MARKUP=1.0 PORT=8080
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
COPY api ./api
EXPOSE 8080
CMD ["sh", "-c", "uvicorn api.app:app --host 0.0.0.0 --port ${PORT}"]
