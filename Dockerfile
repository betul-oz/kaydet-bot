FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
# Yayın (Dokploy/Docker): veri /data hacminde. Şifre (KAYDET_PASSWORD) ve alan adı (KAYDET_ALLOWED_HOSTS) zorunlu.
# Kendi bilgisayarında: -v "$PWD":/data (config.yaml, categories.yaml orada okunur; KAYDET_* değişkenleri yaml'ı ezer).
ENV PYTHONPATH=/app \
    KAYDET_DEPLOY=1 \
    KAYDET_HOST=0.0.0.0 \
    KAYDET_PORT=8000 \
    KAYDET_DB=/data/kaydet.db \
    KAYDET_MEDIA_DIR=/data/media
WORKDIR /data
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=4)"
CMD ["python", "-m", "app"]
