# Storm Events API (FastAPI + AWS Athena + MapLibre)

Containerized FastAPI service to explore **NOAA StormEvents** with **AWS Athena**.  
Supports **offline mode** for local/dev, and serves a minimal **MapLibre GL JS** UI.

## Features
- **Endpoints**
  - `GET /health`
  - `GET /events` — GeoJSON FeatureCollection of points (filters: `start`, `end`, `limit`, `types`, `bbox`)
  - `GET /events/summary` — aggregated counts (`rows: [{key, count}]`)
  - `GET /metrics` — Prometheus metrics (via `starlette-exporter`)
- **Config & Observability**
  - `.env`-driven config (Athena DB, workgroup, S3 output, region, `OFFLINE_MODE`)
  - structlog JSON logs with request IDs (propagates `X-Request-Id`)
  - Prometheus histogram & counters around Athena (when `OFFLINE_MODE=0`)
- **Frontend**
  - StaticMap (MapLibre GL JS) with bbox & date filters (served by FastAPI `StaticFiles`)

---

## Quickstart

### Windows (PowerShell)
```powershell
# 1) Enter the repo and activate venv
cd C:\Users\<you>\Downloads\project_a_stormevents_scaffold\project_a_stormevents
.\.venv\Scripts\Activate.ps1

# 2) Offline dev server (no AWS needed)
$env:OFFLINE_MODE="1"
scripts\dev.ps1
# open http://127.0.0.1:8000/docs
