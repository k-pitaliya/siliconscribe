# ---- Frontend build ----
FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

# ---- Backend + runtime ----
# Pinned to Debian 13 (trixie): its iverilog package is 12.0, the version every probe and test
# was run against. Debian 12 (bookworm) ships 11.0, so an unpinned tag could silently change
# simulator behaviour when the base image moves.
FROM python:3.12-slim-trixie AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    yosys iverilog ca-certificates && \
    rm -rf /var/lib/apt/lists/*
# Fail the build, not the demo, if the simulator is not the tested major version.
RUN iverilog -V | head -1 && iverilog -V | head -1 | grep -q "version 12\."

WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY --from=frontend-build /app/frontend/dist ./static

ENV OFFLINE_MODE=0
ENV PYTHONUNBUFFERED=1

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
