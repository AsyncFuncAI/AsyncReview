---
name: atomgit
description: AI-powered AtomGit PR/Issue reviews with agentic codebase access. Use when the user needs to review AtomGit pull requests, analyze code changes, ask questions about PRs, or get AI feedback on issues.
allowed-tools: Bash(npx asyncreview:*)
---

# AsyncReview CLI for AtomGit

## When to use this skill

Use this skill when the user:
- Asks to review an AtomGit pull request
- Wants AI feedback on code changes in an AtomGit PR
- Needs to check if a PR breaks existing functionality
- Asks questions about an AtomGit issue or PR
- Wants to verify if something was missed in a code change


## How to use this skill

1. **Check prerequisites** — Verify `GEMINI_API_KEY` is set
2. **Check if repo is private** — Determine if `ATOMGIT_TOKEN` is required
3. **Set ATOMGIT_TOKEN if needed** — Get token from AtomGit settings
4. **Get the PR/Issue URL** — Ask user if not provided
5. **Formulate a question** — Convert user's request into a specific question
6. **Run the review command** — Execute `npx asyncreview review --url <URL> -q "<question>"`
7. **Present the results** — Share the AI's findings with sources

## Prerequisites

### 1. Check for API Key (Required)

AsyncReview requires an LLM API key. You can use either **Gemini** or **GLM**:

**Option A: Gemini API**

```bash
export GEMINI_API_KEY="your-gemini-api-key"
```

**Option B: GLM (Zhipu) via Anthropic Compatible API**

```bash
export ZHIPU_API_KEY="your-zhipu-api-key"
export ZHIPU_API_BASE="https://open.bigmodel.cn/api/anthropic"
export MAIN_MODEL="anthropic/glm-5"
export SUB_MODEL="anthropic/glm-5"
```

### 2. Check if Repository is Private (Critical)

**IMPORTANT:** Before reviewing a PR/Issue, you MUST check if the repository is private. If it is, `ATOMGIT_TOKEN` is **REQUIRED**.

#### Step 1: Extract owner and repo from URL

From a URL like `https://atomgit.com/owner/repo/pulls/123`, extract:
- owner: `owner`
- repo: `repo`

#### Step 2: Check repository visibility

**Using curl:**

```bash
# Try to access the repo via AtomGit API with authentication
curl -s -o /dev/null -w "%{http_code}" -H "private-token: $ATOMGIT_TOKEN" https://api.atomgit.com/api/v5/repos/owner/repo
```

**Possible outcomes:**
- `200` → Repository is **public**, `ATOMGIT_TOKEN` is **optional**
- `404` → Repository is **private** or doesn't exist, `ATOMGIT_TOKEN` is **REQUIRED**
- `403` → Rate limited, need `ATOMGIT_TOKEN`

#### Step 3: If private, ensure `ATOMGIT_TOKEN` is set

```bash
# Check if ATOMGIT_TOKEN is already set
echo $ATOMGIT_TOKEN
```

If empty or not set, obtain it:

**Get AtomGit Personal Access Token:**

1. Log in to [https://atomgit.com](https://atomgit.com)
2. Click on your avatar in the top right corner → Personal Settings
3. Find the "Access Tokens" option
4. Create a new token, check `repo` and `pull_request` permissions
5. Set the Token as environment variable:

```bash
export ATOMGIT_TOKEN="your_token_here"

# Verify it's set
echo $ATOMGIT_TOKEN
```

**Then run the review:**

```bash
npx asyncreview review --url <URL> -q "question"
```

## Quick start

```bash
npx asyncreview review --url <PR_URL> -q "question"   # Review a PR
npx asyncreview review --url <PR_URL> --expert        # Expert code review
npx asyncreview review --url <PR_URL> --output markdown     # Markdown output
```

## Core workflow

1. Get PR URL from user
2. Run review with specific question
3. Read the step-by-step reasoning output
4. Model can fetch files outside the diff autonomously

## Commands

### Review

```bash
npx asyncreview review --url <url> -q "question"      # Review with question
npx asyncreview review --url <url> -q "q" --output markdown # Markdown output
npx asyncreview review --url <url> -q "q" -o json     # JSON output
```

**URL formats supported:**
- `https://atomgit.com/owner/repo/pulls/123`
- `https://atomgit.com/owner/repo/issues/456`


## Environment variables

```bash
# Required: LLM API Key (choose one)
GEMINI_API_KEY="your-key"         # For Gemini models
# OR
ZHIPU_API_KEY="your-key"          # For GLM models
ZHIPU_API_BASE="https://open.bigmodel.cn/api/anthropic"

# Optional: For private repos / higher rate limits
ATOMGIT_TOKEN="your-token"
```

## Model Configuration

### Using GLM (Zhipu)

Set environment variables to use GLM models via Anthropic compatible API:

```bash
export ZHIPU_API_KEY="your-zhipu-api-key"
export ZHIPU_API_BASE="https://open.bigmodel.cn/api/anthropic"
export MAIN_MODEL="anthropic/glm-5"
export SUB_MODEL="anthropic/glm-5"
```

### Using Gemini

```bash
export GEMINI_API_KEY="your-gemini-api-key"
export MAIN_MODEL="gemini/gemini-3-pro-preview"
export SUB_MODEL="gemini/gemini-3-flash-preview"
```

## Example: Review a PR

```bash
npx asyncreview review \
  --url https://atomgit.com/owner/repo/pulls/123 \
  -q "Does this change break any existing callers?"
```

**Output Shows:**
- Step number
- 💭 Reasoning (what the AI is thinking)
- 📝 Code (Python being executed)
- 📤 Output (REPL result)
- Final answer with sources

## Example: Check if feature exists elsewhere

```bash
npx asyncreview review \
  --url https://atomgit.com/owner/repo/pulls/123 \
  -q "Fetch src/utils.py and check if deprecated_func is still used"
```

The AI will:
1. Search for the file path
2. Fetch the file via AtomGit API
3. Analyze content in the Python sandbox
4. Report findings with evidence

## Example: Review a Private Repository PR

**Complete workflow for private repositories:**

```bash
# Step 1: Extract owner/repo from URL
# URL: https://atomgit.com/myorg/private-repo/pulls/42
# owner="myorg", repo="private-repo"

# Step 2: Check if repository is private
curl -s -o /dev/null -w "%{http_code}" https://api.atomgit.com/api/v5/repos/myorg/private-repo
# Output: 404 (likely private or doesn't exist)

# Step 3: Ensure ATOMGIT_TOKEN is set
echo $ATOMGIT_TOKEN

## If empty, get from AtomGit settings
export ATOMGIT_TOKEN="your_token_here"

# Step 4: Run the review
npx asyncreview review \
  --url https://atomgit.com/myorg/private-repo/pulls/42 \
  -q "Does this PR introduce any security vulnerabilities?"
```

**If you get a 404 or authentication error:** The repository is likely private, and you need to provide `ATOMGIT_TOKEN`.


## Output formats

| Format | Flag | Description |
|--------|------|-------------|
| Pretty | (default) | Rich terminal output with boxes |
| Markdown | `--output markdown` or `-o markdown` | Markdown formatted |
| JSON | `--output json` or `-o json` | Machine-readable |

## Expert Code Review

Use `--expert` flag for comprehensive PR reviews covering SOLID principles, security, performance, and code quality:

```bash
# Full expert review (no question needed)
npx asyncreview review --url <PR_URL> --expert

# Expert review with additional custom question
npx asyncreview review --url <PR_URL> --expert -q "Also check for breaking API changes"
```

**Expert review analyzes:**
- **SOLID Principles** - SRP, OCP, LSP, ISP, DIP violations
- **Security** - XSS, injection, auth gaps, race conditions, secrets
- **Code Quality** - Error handling, N+1 queries, boundary conditions
- **Removal Candidates** - Dead code, unused imports

**Output includes:**
- Severity-tagged findings (P0 Critical → P3 Low)
- Suggested fixes for P0/P1 issues
- Overall assessment: APPROVE / REQUEST_CHANGES / COMMENT
