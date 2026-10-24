FROM python:3.12-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
WORKDIR /app
ARG VERSION=0.2.0
ARG VCS_REF=unknown
LABEL org.opencontainers.image.title="Wyoming Hush Proxy" \
      org.opencontainers.image.description="Local streaming speech enhancement proxy for Wyoming STT services" \
      org.opencontainers.image.source="https://github.com/Dominik-1980/wyoming-hush-proxy" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.version=$VERSION \
      org.opencontainers.image.revision=$VCS_REF
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && mkdir /data && chown 99:100 /data
COPY hush_proxy /app/hush_proxy
COPY licenses /app/licenses
COPY NOTICE /app/NOTICE
COPY LICENSE /app/LICENSE
COPY vendor-manifest.json model-checksums.json /app/
USER 99:100
EXPOSE 10322 10323
HEALTHCHECK --interval=30s --timeout=3s --start-period=30s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('WEB_PORT','10323')+'/healthz',timeout=2)"
CMD ["python", "-m", "hush_proxy"]
