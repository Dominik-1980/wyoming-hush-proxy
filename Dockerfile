FROM python:3.12-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
WORKDIR /app
ARG VERSION=0.3.1
ARG VCS_REF=local
LABEL org.opencontainers.image.title="Wyoming Noise Cancelling Proxy" \
      org.opencontainers.image.source="https://github.com/Dominik-1980/wyoming-noise-cancelling-proxy" \
      org.opencontainers.image.description="Streaming DTLN and Hush, individually selectable, for Wyoming STT" \
      org.opencontainers.image.licenses="Apache-2.0 AND MIT" \
      org.opencontainers.image.version=$VERSION \
      org.opencontainers.image.revision=$VCS_REF
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && mkdir /data && chown 99:100 /data
COPY dtln_proxy /app/dtln_proxy
COPY licenses /app/licenses
COPY assets /app/assets
COPY NOTICE LICENSE dtln-models.json model-checksums.json verify_models.py /app/
RUN python verify_models.py
USER 99:100
EXPOSE 10326 10327
HEALTHCHECK --interval=30s --timeout=3s --start-period=30s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('WEB_PORT','10327')+'/healthz',timeout=2)"
CMD ["python", "-m", "dtln_proxy"]
