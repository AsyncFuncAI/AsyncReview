#!/bin/bash

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== AsyncReview Setup ===${NC}"

# 1. Prerequisite Checks
check_cmd() {
    if ! command -v $1 &> /dev/null; then
        echo -e "${RED}Error: $1 is not installed.${NC}"
        echo -e "Please install $1 to continue."
        exit 1
    fi
}

echo -e "${YELLOW}Checking prerequisites...${NC}"
check_cmd uv
check_cmd deno

# Check node/bun
HAS_BUN=false
if command -v bun &> /dev/null; then
    HAS_BUN=true
    echo -e "${GREEN}✓ bun found${NC}"
elif command -v npm &> /dev/null; then
    echo -e "${GREEN}✓ npm found${NC}"
else
    echo -e "${RED}Error: Neither bun nor npm found.${NC}"
    exit 1
fi

echo -e "${GREEN}✓ uv found${NC}"
echo -e "${GREEN}✓ deno found${NC}"

# 2. Environment Setup
if [ ! -f .env ]; then
    echo -e "${YELLOW}Creating .env from example...${NC}"
    cp .env.example .env
    echo -e "${YELLOW}⚠️  PLEASE EDIT .env AND ADD YOUR API KEYS ⚠️${NC}"
    read -p "Press Enter to continue after editing .env (or Ctrl+C to abort)..."
fi

# 3. Backend Setup
echo -e "${BLUE}Setting up Backend (Python/uv)...${NC}"
uv venv
# Install dependencies into the virtual environment
uv pip install -e .

# 3b. Pre-cache Deno dependencies (pyodide for RLM sandboxed execution)
echo -e "${BLUE}Caching Deno dependencies (pyodide)...${NC}"
deno cache npm:pyodide/pyodide.js 2>/dev/null || echo -e "${YELLOW}Note: pyodide will be cached on first run${NC}"
echo -e "${GREEN}✓ Deno dependencies ready${NC}"

# 4. Frontend Setup
echo -e "${BLUE}Setting up Frontend...${NC}"
cd web
if [ "$HAS_BUN" = true ]; then
    echo "Installing with bun..."
    bun install
    FRONTEND_CMD="bun dev"
else
    echo "Installing with npm..."
    npm install
    FRONTEND_CMD="npm run dev"
fi
cd ..

# 5. Execution
echo -e "${GREEN}All systems go! Starting servers...${NC}"
echo -e "Backend: http://localhost:8000"
echo -e "Frontend: http://localhost:3000"

# Kill all child processes on exit
trap 'kill 0' SIGINT

# Start Backend
uv run uvicorn cr.server:app --reload --port 8000 &

# Start Frontend
cd web
$FRONTEND_CMD --port 3000 &

# Wait for both
wait
