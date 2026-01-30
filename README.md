# AsyncReview
Open-source Agentic code review tool inspired by DevinReview, using Recursive Language Models (RLM)

## Prerequisites


- **Python 3.11+**
- **Node.js** (or Bun)
- **uv** (recommended for Python package management)
- **Deno** (Required for sandboxed code execution)


https://github.com/user-attachments/assets/e17951e6-d73d-4cc0-8199-66c7e02f049f


<img width="2000" height="1296" alt="image" src="https://github.com/user-attachments/assets/41955d76-00d9-4987-9ea8-3e5243c895f7" />


<img width="1146" height="609" alt="Screenshot 2026-01-24 at 10 37 53 PM" src="https://github.com/user-attachments/assets/1b67cf2d-6923-46b8-8fac-83e6bf707ce3" />

## Setup

1. **Install Backend (cr)**
   ```bash
   # Using uv (Recommended)
   uv pip install -e .

   # Or standard pip
   pip install -e .

   # Pre-cache Deno dependencies (speeds up first run)
   deno cache npm:pyodide/pyodide.js
   ```

2. **Install Frontend (web)**
   ```bash
   cd web
   bun install  # or npm install
   ```

3. **Environment Setup**
   Copy `.env.example` to `.env` and fill in your API keys:
   ```bash
   cp .env.example .env
   ```
   **Required variables:**
   - `GEMINI_API_KEY`: Your Google Gemini API key.
   - `GITHUB_TOKEN`: GitHub Token (for PR access & higher rate limits).

## Running

### 1. Start the API Server
```bash
cr serve
# or
uv run uvicorn cr.server:app --reload
```
Server runs at `http://127.0.0.1:8000`.

### 2. Start the Web UI
```bash
cd web
bun dev
```
Open `http://localhost:3000` in your browser.

## Quick Start
 
 No installation needed! Just use `npx`:
 
 ```bash
 # Review a GitHub PR
 npx asyncreview review --url https://github.com/org/repo/pull/123 -q "Any security concerns?"
 ```
 
 ## CLI Usage

You can also use the tool directly from the terminal:

### `cr` - Local Codebase Review
- **Interactive Q&A**: `cr ask`
- **One-shot Review**: `cr review -q "What does this repo do?"`
- **Help**: `cr --help`

### `npx asyncreview` - GitHub PR/Issue Review
 
 Review GitHub PRs and Issues directly from the command line:
 
 ```bash
 # Review a PR
 npx asyncreview review --url https://github.com/org/repo/pull/123 -q "Any security concerns?"

# Review with markdown output (great for docs/skills)
# Review with markdown output (great for docs/skills)
npx asyncreview review --url https://github.com/org/repo/pull/123 \
  -q "Summarize the changes" \
  --output markdown

# Quiet mode for scripting (no progress bars)
# Quiet mode for scripting (no progress bars)
npx asyncreview review --url https://github.com/org/repo/pull/123 \
  -q "What does this PR do?" \
  --quiet --output json

# Use a specific model
# Use a specific model
npx asyncreview review --url https://github.com/org/repo/pull/123 \
  -q "Deep code review" \
  --model gemini-3.0-pro-preview
```

**Options:**
- `--url, -u`: GitHub PR or Issue URL (required)
- `--question, -q`: Question to ask (required)
- `--output, -o`: Output format: `text`, `markdown`, `json` (default: text)
- `--quiet`: Suppress progress output
- `--model, -m`: Model override (default: from .env)

## Troubleshooting

### Deno/Pyodide Issues
If you see errors like `Could not find npm:pyodide`, run:
```bash
deno cache npm:pyodide/pyodide.js
```

### Slow First Run
The first run may take longer as Deno downloads and compiles pyodide (~50MB). Subsequent runs are instant.
