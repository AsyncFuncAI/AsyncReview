<p align="center">
  <img width="588" height="596" alt="AsyncReview" src="https://github.com/user-attachments/assets/daad14de-119f-45a8-9ad9-db6649dc9c44" />
</p>

<h1 align="center">AsyncReview</h1>

<p align="center">
  <strong>Agentic Code Review for GitHub PRs, Issues, and Local Codebases</strong>
</p>

<p align="center">
  <a href="https://www.npmjs.com/package/asyncreview"><img src="https://img.shields.io/npm/v/asyncreview" alt="npm version" /></a>
  <a href="https://github.com/AsyncFuncAI/AsyncReview/blob/main/LICENSE"><img src="https://img.shields.io/github/license/AsyncFuncAI/AsyncReview" alt="License: MIT" /></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+" /></a>
  <a href="https://nodejs.org/"><img src="https://img.shields.io/badge/node-18%2B-green" alt="Node 18+" /></a>
</p>

---

AsyncReview uses **Recursive Language Models (RLM)** to go beyond simple diff analysis. It autonomously explores your repository, fetches relevant context, and verifies its findings in a secure sandbox before answering.

```
       User Request
     "Verify this PR/Issue"
           |
           v
+-------------------------------------------------------+
|  AsyncReview Agent (Recursive Loop)                   |
|                                                       |
|  1. Reason & Plan                                     |
|  2. Generate Python Code                              |
|       |                                               |
|       v                                               |
|  3. [Deno/Pyodide Sandbox]                            |
|     (Executes logic + tool commands)                  |
|       |                                               |
|       v                                               |
|  4. Tool Interceptor <-----> [GitHub API / Local FS]  |
|     (FETCH_FILE, SEARCH_CODE, LIST_DIRECTORY)         |
|       |                                               |
|       v                                               |
|  5. Observe Result & Repeat Recursively               |
+-------------------------------------------------------+
           |
           v
      Final Answer with Citations
```

## Why AsyncReview?

Most AI review tools only look at the lines changed in a Pull Request (the diff). This leads to shallow feedback and hallucinations about files that don't exist.

| Other Code Review Tools | AsyncReview |
|-------------|-------------|
| **Limited Context:** Only sees the git diff | **Full Context:** Can read any file in the repo to understand dependencies |
| **Static Analysis:** Guesses how code works | **Agentic Analysis:** Executes search queries and verification scripts |
| **Hallucinations:** Invents library methods | **Grounded:** Cites existing file paths and line numbers |
| **Simple Prompts:** One-shot generation | **Recursive Reasoning:** Thinks, plans, and iterates before answering |

## Quick Start

No installation required. Run directly with npx:

```bash
# Review a GitHub PR
npx asyncreview review --url https://github.com/org/repo/pull/123 -q "Check for breaking changes"

# Review a GitHub Issue
npx asyncreview review --url https://github.com/org/repo/issues/42 -q "What's needed to implement this?"
```

> You need a [Gemini API key](https://aistudio.google.com/app/apikey) set as `GEMINI_API_KEY`.

## Usage

### Public Repositories

```bash
export GEMINI_API_KEY="your-key"
npx asyncreview review --url https://github.com/org/repo/pull/123 -q "Review this"
```

### Private Repositories

For private repos, you also need a GitHub token:

```bash
# If you have GitHub CLI installed
export GITHUB_TOKEN=$(gh auth token)

# Or set it manually (https://github.com/settings/tokens)
export GITHUB_TOKEN="ghp_..."

npx asyncreview review --url https://github.com/org/repo/pull/456 -q "Security audit"
```

### Expert Code Review

Use the `--expert` flag for comprehensive reviews covering SOLID principles, security, performance, and code quality:

```bash
# Full expert review (no question needed)
npx asyncreview review --url https://github.com/org/repo/pull/123 --expert

# Expert review with additional question
npx asyncreview review --url https://github.com/org/repo/pull/123 --expert -q "Also check for breaking API changes"
```

Expert reviews analyze against built-in checklists:

- **SOLID & Architecture** -- SRP, OCP, LSP, ISP, DIP violations
- **Security & Reliability** -- XSS, injection, auth gaps, race conditions, secrets exposure
- **Code Quality** -- Error handling, N+1 queries, boundary conditions
- **Removal Candidates** -- Dead code, unused imports, deprecated patterns

Findings are severity-tagged (P0 Critical through P3 Low) with fix suggestions for P0/P1 issues.

### Output Formats

```bash
npx asyncreview review --url <URL> -q "Review" --output markdown   # Markdown
npx asyncreview review --url <URL> -q "Review" --output json       # JSON (for scripting)
npx asyncreview review --url <URL> -q "Review" --quiet             # Suppress progress, print result only
```

### Local Codebase Review

Review a local folder directly without going through GitHub:

```bash
npx asyncreview review --path ./my-project -q "Find potential bugs in this codebase"
```

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GEMINI_API_KEY` | Yes | -- | [Google AI Studio](https://aistudio.google.com/app/apikey) API key |
| `GITHUB_TOKEN` | For private repos | -- | GitHub personal access token |
| `MAIN_MODEL` | No | `gemini/gemini-3-pro-preview` | Primary LLM (LiteLLM format) |
| `SUB_MODEL` | No | `gemini/gemini-3-flash-preview` | Secondary LLM for sub-tasks |
| `MAX_ITERATIONS` | No | `20` | Max RLM reasoning iterations |
| `MAX_LLM_CALLS` | No | `25` | Max total LLM calls per review |
| `MAX_FILE_BYTES` | No | `200000` | Max bytes per file in snapshot |
| `MAX_TOTAL_BYTES` | No | `5000000` | Max total bytes for snapshot |
| `INCLUDE_GLOBS` | No | -- | Comma-separated file patterns to include |
| `EXCLUDE_GLOBS` | No | -- | Comma-separated file patterns to exclude |

## For Agents (Claude, Cursor, OpenCode, Gemini, Codex, etc.)

AsyncReview is designed to be used as a **Skill** by other agentic providers, allowing them to "see" and "reason" about codebases they don't have local access to.

### Install via Skills CLI

```bash
npx skills add AsyncFuncAI/AsyncReview
```

This works with [vercel/skills](https://github.com/vercel/skills) compatible agents.

### Manual Setup

Point your agent to the skill definition file: [`skills/asyncreview/SKILL.md`](skills/asyncreview/SKILL.md)

## Architecture

AsyncReview consists of three main components:

```
AsyncReview/
|
|-- npx/                  # Zero-install npx CLI (TypeScript launcher + bundled Python runtime)
|   |-- dist/             #   Compiled launcher (downloads runtime on first run)
|   +-- python/           #   Bundled Python runtime (RLM engine, tools, checklists)
|
|-- cr/                   # Python backend (installable `cr` CLI + FastAPI server)
|   |-- cli.py            #   Local codebase review CLI (interactive & one-shot)
|   |-- server.py         #   FastAPI server for the web UI
|   |-- rlm_runner.py     #   DSPy RLM orchestration with Deno/Pyodide sandbox
|   |-- diff_rlm.py       #   PR diff analysis modules (AutoReview + Q&A)
|   |-- github.py         #   GitHub API integration
|   |-- snapshot.py        #   Codebase snapshot builder with symbol extraction
|   +-- suggestions.py    #   Follow-up suggestion generator
|
|-- web/                  # React + Vite frontend
|   +-- src/
|       |-- App.tsx       #   Main app: PR loading, diff viewer, chat panel
|       +-- components/   #   DiffViewer, ChatPanel, BugsPanel, FlagsPanel, PRSummary
|
|-- cli/                  # Standalone asyncreview CLI (used by npx runtime)
|-- skills/               # Agent skill definitions (SKILL.md for Vercel Skills)
|-- scripts/              # Build & install scripts for runtime artifacts
+-- tests/                # Test suite
```

### How It Works

1. **Input**: User provides a GitHub PR/Issue URL (or local path) and a question
2. **Context Building**: AsyncReview fetches the diff, file metadata, commits, and comments from GitHub (or reads local files)
3. **RLM Loop**: The [DSPy RLM](https://github.com/stanfordnlp/dspy) engine enters a recursive reasoning loop:
   - **Reason & Plan**: The LLM analyzes the context and decides what to investigate
   - **Generate Code**: It writes Python code to execute (search, fetch files, run queries)
   - **Sandbox Execution**: Code runs in a Deno/Pyodide sandbox with tool interception
   - **Observe & Repeat**: Results feed back into the next iteration
4. **Tools Available to the Agent**:
   - `FETCH_FILE` -- Read any file in the repo (not just the diff)
   - `SEARCH_CODE` -- Search the codebase with pattern matching
   - `LIST_DIRECTORY` -- Explore the repo structure
5. **Output**: Final answer with citations pointing to specific file paths and line numbers

### Tech Stack

| Layer | Technology |
|-------|------------|
| LLM Framework | [DSPy](https://github.com/stanfordnlp/dspy) (RLM module) |
| AI Model | Google Gemini (via LiteLLM) |
| Code Sandbox | [Deno](https://deno.land/) + [Pyodide](https://pyodide.org/) |
| Backend | [FastAPI](https://fastapi.tiangolo.com/) + SSE streaming |
| Frontend | [React](https://react.dev/) + [Vite](https://vite.dev/) |
| CLI | [Rich](https://github.com/Textualize/rich) (Python) + [Commander](https://github.com/tj/commander.js) (Node) |

## Advanced Setup

To run the full backend server and web interface locally, see the [Installation Guide](INSTALLATION.md).

Quick start for local development:

```bash
# One-command setup and launch
./start.sh
```

Or manually:

```bash
# Backend
uv pip install -e .
deno cache npm:pyodide/pyodide.js
cr serve

# Frontend (in a second terminal)
cd web && bun install && bun dev
```

Server runs at `http://localhost:8000`, frontend at `http://localhost:3000`.

## Development

```bash
# Install dev dependencies
uv pip install -e ".[dev]"

# Run tests
uv run pytest tests/ -v

# Lint & format
ruff check .
mypy cr/

# Build npx package
cd npx && npm install && npm run build
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for more details.

## Supported Platforms

Runtime binaries are built for:

- macOS (Apple Silicon -- `darwin-arm64`)
- macOS (Intel -- `darwin-x64`)
- Linux (`linux-x64`)

The runtime is automatically downloaded on first `npx asyncreview` run.

## License

[MIT](LICENSE) 😊
