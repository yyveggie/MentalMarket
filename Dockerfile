FROM node:20-slim AS frontend
WORKDIR /build
COPY app/dashboard/frontend/package.json app/dashboard/frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY app/dashboard/frontend/ .
RUN npm run build

FROM python:3.12-slim

RUN groupadd -r mm && useradd -r -g mm -d /app mm

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    rm -rf /root/.cache/pip

COPY --chown=mm:mm app/ app/
COPY --chown=mm:mm prompts/ prompts/
COPY --chown=mm:mm tools/ tools/
COPY --chown=mm:mm scripts/ scripts/
COPY --chown=mm:mm data/ data/
COPY --chown=mm:mm run.py .
COPY --chown=mm:mm config.yaml .
COPY --chown=mm:mm config_100.yaml .

COPY --from=frontend --chown=mm:mm /static/ app/dashboard/static/

RUN mkdir -p runs && chown mm:mm runs

USER mm

ENV PYTHONUNBUFFERED=1
EXPOSE 8765
VOLUME ["/app/runs"]

STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/state')" || exit 1

ENTRYPOINT ["python", "run.py"]
