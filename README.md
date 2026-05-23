# Project A - StormEvents API

A containerized FastAPI application for exploring NOAA StormEvents data through API endpoints and a lightweight web map interface.

This project demonstrates a cloud-oriented geospatial data workflow using Python, Docker, FastAPI, AWS Athena, Glue Data Catalog, and S3-style query outputs.

## Features

- FastAPI backend for querying storm event records
- Date, bounding box, event type, and limit-based filtering
- Summary endpoint for grouping events by fields such as event type
- Lightweight MapLibre web UI for visualizing events on a map
- Docker Compose setup for local development
- AWS Athena / Glue / S3 configuration through environment variables
- Example IAM policy for least-privilege-style access
- Basic API tests
- Architecture and setup documentation

## Project structure

```text
.
├── .github/             # GitHub workflows, issue templates, and PR template
├── api/                 # FastAPI app, Dockerfile, and backend requirements
├── web/                 # MapLibre frontend
├── etl/                 # ETL scripts
├── infra/sql/           # Athena SQL setup and smoke-test queries
├── scripts/             # Helper scripts
├── tests/               # Pytest tests
├── docs/                # Architecture docs, ADRs, and IAM example policy
├── assets/              # Screenshots and images
├── data/                # Local/generated data; large files are not committed
├── docker-compose.yml
└── README.md
```

## API endpoints

| Endpoint | Purpose |
|---|---|
| `GET /health` | Check whether the API is running |
| `GET /events?start=YYYY-MM-DD&end=YYYY-MM-DD&bbox=minLon,minLat,maxLon,maxLat&limit=100` | Query storm events with date, bounding box, and limit filters |
| `GET /events/summary?groupby=type` | Return grouped summary results, such as counts by event type |

## Quickstart

Build and run the API:

```bash
docker compose up --build
```

Open the API docs:

```text
http://localhost:8000/docs
```

Open the web map:

```text
web/index.html
```

## Environment variables

The API reads configuration from `docker-compose.yml` and `.env`.

Example variables:

```text
AWS_PROFILE=stormevents-dev
AWS_REGION=us-east-2
AWS_DEFAULT_REGION=us-east-2
ATHENA_WORKGROUP=primary
ATHENA_DATABASE=stormevents
ATHENA_TABLE=stormevents_v
ATHENA_OUTPUT_S3=s3://your-athena-results-bucket/athena-results/
```

Do not commit real AWS credentials or private `.env` files.

Use `.env.example` to document required variables without exposing secrets.

## Data

Large generated data files are not committed to this repository.

Small sample files for local testing and README examples are stored in:

```text
data/sample/
```

The full NOAA StormEvents dataset should be generated or queried through the configured data workflow rather than stored directly in the repository.

## IAM and security

This repository includes an example IAM policy under:

```text
docs/iam/stormevents-api-policy.example.json
```

The public example policy should use placeholders such as:

```text
<ACCOUNT_ID>
<ATHENA_RESULTS_BUCKET>
```

instead of real AWS account IDs, bucket names, or private environment-specific values.

## Development notes

The API service is built from the `api/` folder:

```text
api/
├── Dockerfile
├── app.py
└── requirements.txt
```

The root `docker-compose.yml` builds the API container using:

```yaml
build:
  context: ./api
```

This means the backend dependencies are installed from:

```text
api/requirements.txt
```

## What I learned

Through this project, I practiced connecting backend API design, cloud data querying, Docker-based development, IAM/security awareness, and geospatial visualization into a maintainable application workflow.
