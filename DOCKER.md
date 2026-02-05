# Docker Setup for AsyncReview

This guide explains how to run AsyncReview using Docker, both for production (immutable usage) and local development.

## Prerequisites

- **Docker** and **Docker Compose** installed on your machine.
- A `.env` file with your API keys (see [README.md](README.md) or copy `.env.example`).

**Note:** You *must* create a `.env` file before running any Docker commands.
```bash
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
```

## Quick Start (Production/User Mode)

To run the application in a stable, immutable container environment using the convenience Makefile command:

```bash
make docker-up
```

Alternatively, using Docker Compose directly:
```bash
docker compose up --build
```

- **Web UI:** http://localhost:3000
- **API:** Proxied via the Web UI at http://localhost:3000/api
  - Note: The backend service is not directly exposed to the host in production mode.

To stop the application:
```bash
docker compose down
```

## Local Development

To run the application in development mode with hot-reloading (changes to your code are immediately reflected):

```bash
make docker-dev
```

Alternatively, using Docker Compose directly (requires both files):
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

- **Web UI:** http://localhost:5173 (Vite dev server)
- **API:** http://localhost:8000 (Direct access for debugging)

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
