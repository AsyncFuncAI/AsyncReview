# Installation Guide

This guide covers advanced installation and setup for running AsyncReview locally with the full web UI and API server.

<img width="2000" height="1296" alt="image" src="https://github.com/user-attachments/assets/41955d76-00d9-4987-9ea8-3e5243c895f7" />


<img width="1146" height="609" alt="Screenshot 2026-01-24 at 10 37 53 PM" src="https://github.com/user-attachments/assets/1b67cf2d-6923-46b8-8fac-83e6bf707ce3" />


> **Note:** If you just want to review GitHub PRs/Issues, you don't need to install anything! Just use `npx asyncreview` (see main [README](README.md)).

## Prerequisites

- **Python 3.11+**
- **Node.js 18+** (or Bun)
- **uv** (recommended for Python package management)
- **Deno** (Required for sandboxed code execution)

### Installing Prerequisites

**macOS:**
```bash
# Install uv (Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install Deno
curl -fsSL https://deno.land/install.sh | sh

# Install Bun (optional, alternative to npm)
curl -fsSL https://bun.sh/install | bash
```

**Linux:**
```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install Deno
curl -fsSL https://deno.land/install.sh | sh
```

**Windows:**
```powershell
# Install uv
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Install Deno
irm https://deno.land/install.ps1 | iex
```

## Full Setup

### 1. Clone the Repository

```bash
git clone https://github.com/AsyncFuncAI/AsyncReview.git
cd AsyncReview
```

### 2. Install Backend (cr)

```bash
# Using uv (Recommended)
uv pip install -e .

# Or standard pip
pip install -e .

# Pre-cache Deno dependencies (speeds up first run)
deno cache npm:pyodide/pyodide.js
```

### 3. Install Frontend (web)

```bash
cd web
bun install  # or npm install
```

### 4. Environment Setup

Copy `.env.example` to `.env` and fill in your API keys:

```bash
cp .env.example .env
```

**Required environment variables:**

```bash
# .env file
GEMINI_API_KEY=your_gemini_api_key_here
GITHUB_TOKEN=your_github_token_here  # Optional for npx, required for web UI
```

**Getting your API keys:**

- **Gemini API Key**: Get from [Google AI Studio](https://aistudio.google.com/app/apikey)
- **GitHub Token**: 
  - Quick: `gh auth token` (if you have GitHub CLI)
  - Manual: [Create Personal Access Token](https://github.com/settings/tokens)
    - Select `repo` scope for private repositories
    - Select `public_repo` for public repositories only

## Running AsyncReview Locally

### Option 1: Using the API Server + Web UI

**Start the API Server:**
```bash
cr serve
# or
uv run uvicorn cr.server:app --reload
```

Server runs at `http://127.0.0.1:8000`.

**Start the Web UI:**
```bash
cd web
bun dev  # or npm run dev
```

Open `http://localhost:3000` in your browser.

### Option 2: Using the CLI (Local Codebase)

The `cr` CLI allows you to review local codebases:

```bash
# Interactive Q&A mode
cr ask

# One-shot review
cr review -q "What does this repo do?"

# Review specific files
cr review -q "Analyze src/main.py for bugs"

# Get help
cr --help
```

### Option 3: Using npx (GitHub PRs/Issues)

No installation needed - works from anywhere:

```bash
npx asyncreview review --url https://github.com/org/repo/pull/123 -q "Review this PR"
```

See the main [README](README.md) for npx usage details.

## Troubleshooting

### Deno/Pyodide Issues

If you see errors like `Could not find npm:pyodide`, run:
```bash
deno cache npm:pyodide/pyodide.js
```

### Slow First Run

The first run may take longer as Deno downloads and compiles Pyodide (~50MB). Subsequent runs are instant.

### Python Version Issues

Ensure you're using Python 3.11+:
```bash
python --version
# or
python3 --version
```

If needed, install Python 3.11+ from [python.org](https://www.python.org/downloads/).

### uv Installation Issues

If `uv` commands fail, ensure it's in your PATH:
```bash
# Add to ~/.bashrc or ~/.zshrc
export PATH="$HOME/.cargo/bin:$PATH"
```

### Port Already in Use

If port 8000 is already in use:
```bash
# Use a different port
uvicorn cr.server:app --port 8001
```

## Development

### Running Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_github.py

# Run with coverage
pytest --cov=cr
```

### Type Checking

```bash
# Run mypy
mypy cr/
```

### Code Formatting

```bash
# Format with black
black cr/ tests/

# Sort imports
isort cr/ tests/
```

## Architecture Overview

AsyncReview consists of three main components:

1. **`cr` (Python Backend)**: Core RLM engine with Pyodide sandbox
2. **`web` (Next.js Frontend)**: Interactive web UI for PR reviews
3. **`npx asyncreview` (CLI)**: Zero-install command for GitHub PR/Issue reviews

For more details, see the [main README](README.md).
