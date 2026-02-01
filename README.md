# AsyncReview

**Agentic Code Review for GitHub PRs and Issues**

AsyncReview uses Recursive Language Models (RLM) to go beyond simple diff analysis. It autonomously explores your repository, fetches relevant context, and verifies its findings in a secure sandbox before answering.

```
       User Request
     "Verify this PR"
           │
           ▼
+-------------------------+       +-------------------------+
|    AsyncReview Agent    |       |     GitHub Repository   |
|                         |       |                         |
|   1. Analyze Diff       |       |   [Code] [Issues]       |
|   2. Formulate Plan     |------>|   [PRs]  [Comments]     |
|   3. Explore Codebase   |<------|                         |
|   4. Verify in Sandbox  |       |                         |
+-------------------------+       +-------------------------+
           │     ▲
           ▼     │ (Recursive Loop)
      [Grounded Answer]
```

#
<img width="588" height="596" alt="image" src="https://github.com/user-attachments/assets/daad14de-119f-45a8-9ad9-db6649dc9c44" />


## Why AsyncReview?

Most AI review tools only look at the lines changed in a Pull Request (the diff). This leads to shallow feedback and hallucinations about files that don't exist. AsyncReview takes a different approach.

| Other Tools | AsyncReview |
|-------------|-------------|
| **Limited Context:** Only sees the git diff | **Full Context:** Can read any file in the repo to understand dependencies |
| **Static Analysis:** Guesses how code works | **Agentic Analysis:** Can execute search queries and run verification scripts |
| **Hallucinations:** Invents library methods | **Grounded:** cites existing file paths and lines |
| **Simple Prompts:** One-shot generation | **Recursive Reasoning:** Thinks, plans, and iterates before answering |

## Quick Start

No installation required. Run directly with npx:

```bash
npx asyncreview review --url https://github.com/org/repo/pull/123 -q "Check for breaking changes"
```

## Usage

### Public Repositories

For public repos, you only need a Gemini API key.

```bash
export GEMINI_API_KEY="your-key"
npx asyncreview review --url https://github.com/org/repo/pull/123 -q "Review this"
```

### Private Repositories

For private repos, you also need a GitHub token.

1. **Set your GitHub Token** (or use the `--github-token` flag)
   ```bash
   # If you have GitHub CLI installed
   export GITHUB_TOKEN=$(gh auth token)
   
   # Or manually set it
   export GITHUB_TOKEN="ghp_..."
   ```

2. **Run the review**
   ```bash
   npx asyncreview review --url https://github.com/org/private-repo/pull/456 -q "Security audit"
   ```

## Configuration

**Required:**
- **Gemini API Key:** Get one from Google AI Studio. Set as `GEMINI_API_KEY`.

**Optional:**
- **GitHub Token:** Required for private repositories to access file contents. Set as `GITHUB_TOKEN`.

## For AI Agents

AsyncReview is designed to be used as a **Skill** by other AI agents (like Claude Desktop or Gemini Code Assist). It allows them to "see" and "reason" about codebases they don't have local access to.

### ⚡️ Easiest Way: Install via Skills CLI

Run this command to automatically add AsyncReview to your agent's capabilities:

```bash
npx skills add AsyncFuncAI/AsyncReview
```

This works with [vercel/skills](https://github.com/vercel/skills) compatible agents.

### Manual Setup

If you prefer manual configuration, point your agent to the skill definition file:
`skills/asyncreview/SKILL.md`

## Advanced Setup

To run the full backend server or web interface locally, please see the [Installation Guide](INSTALLATION.md).

## License

MIT
