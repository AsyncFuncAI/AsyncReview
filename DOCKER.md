# Docker Setup for AsyncReview

This guide explains how to run AsyncReview using Docker, both for production (immutable usage) and local development.

## Prerequisites

- **Docker** and **Docker Compose** installed on your machine.
- A `.env` file with your API keys (see [README.md](README.md) or copy `.env.example`).

## Quick Start (Production/User Mode)

To run the application in a stable, immutable container environment:

1. Ensure your `.env` file is populated.
2. Run:

```bash
docker compose up --build
```

- The Web UI will be available at: http://localhost:3000
- The Backend API will be available at: http://localhost:8000

To stop the application:
```bash
docker compose down
```

## Local Development

To run the application in development mode with hot-reloading (changes to your code are immediately reflected):

1. Run:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

- The Web UI (Vite dev server) will be available at: http://localhost:5173
- The Backend API (Uvicorn with reload) will be available at: http://localhost:8000

*Note: In development mode, the `web/` directory and the root directory are mounted into the containers. Changes you make locally will trigger reloads.*

## Running CLI Commands

You can run the `cr` CLI tool inside the backend container.

**In Production Mode:**
```bash
docker compose run --rm backend cr --help
docker compose run --rm backend cr review --url https://github.com/org/repo/pull/123
```

**In Development Mode:**
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm backend cr --help
```

## Troubleshooting

### Port Conflicts
If port 3000, 8000, or 5173 are in use, you can modify the ports in `docker-compose.yml` or `docker-compose.dev.yml`.

### Deno/Pyodide Issues
The backend container installs Deno and caches the Pyodide environment during the build. If you encounter issues, try rebuilding:
```bash
docker compose build --no-cache backend
```

### Dependencies
If you add new Python dependencies to `pyproject.toml`, you must rebuild the backend container:
```bash
docker compose build backend
```
In development mode, since the source is mounted but dependencies are installed in the system python path, a rebuild is usually required to install new dependencies.
