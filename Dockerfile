FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    COVERS_CONFIG=/config/config.json

RUN useradd --uid 1000 --create-home app \
 && mkdir -p /data /config \
 && chown app:app /data

WORKDIR /app
COPY covers.py .

USER app
VOLUME /data
EXPOSE 8099

HEALTHCHECK --interval=60s --timeout=5s --start-period=30s \
  CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/health'%os.environ.get('PORT','8099'),timeout=3)" || exit 1

CMD ["python", "covers.py", "serve"]
