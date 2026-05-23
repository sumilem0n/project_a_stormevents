# Project A - StormEvents API

A containerized FastAPI application for exploring NOAA StormEvents data through API endpoints and a lightweight web map interface.

This project demonstrates a cloud-oriented geospatial data workflow using Python, Docker, FastAPI, AWS Athena, Glue Data Catalog, and S3-style query outputs.

## Features

- FastAPI backend for querying storm event records
- Date, bounding box, event type, and limit-based filtering
- Summary endpoint for grouping events by fields such as event type
- Lightweight MapLibre web UI for visualizing events on a map
- Docker Compose setup for local development
- AWS Athena/Glue/S3 configuration through environment variables
- Example IAM policy for least-privilege-style access
- Basic tests for API health and metrics
- Documentation for architecture and setup

## Project structure

```text
.
├── api/                 # FastAPI app, Dockerfile, backend requirements
├── web/                 # MapLibre frontend
├── etl/                 # ETL scripts
├── infra/sql/           # Athena SQL setup and smoke-test queries
├── scripts/             # Helper scripts
├── tests/               # Pytest tests
├── docs/                # Architecture docs, ADRs, IAM example policy
├── assets/              # Screenshots and images
├── data/                # Local/generated data; large files are not committed
├── docker-compose.yml
└── README.md
