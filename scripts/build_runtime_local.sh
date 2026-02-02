#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./scripts/build_runtime_local.sh 1.2.3
#
# Output:
#   dist/asyncreview-runtime-v<version>-<platform>.tar.gz
#
# Requirements:
#   - python3.11+
#   - pip available (python -m pip)
#   - curl
#   - tar

VERSION="${1:?version required, e.g. 1.2.3}"

PLATFORM="$(uname -s | tr '[:upper:]' '[:lower:]')" # darwin | linux
ARCH="$(uname -m)"
case "$ARCH" in
  arm64|aarch64) ARCH="arm64" ;;
  x86_64) ARCH="x64" ;;
  *) echo "Unsupported arch: $ARCH" >&2; exit 1 ;;
esac
PLATFORM_KEY="${PLATFORM}-${ARCH}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$ROOT_DIR/dist"
STAGE_DIR="$ROOT_DIR/.runtime_stage/${PLATFORM_KEY}"

rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR/bin" "$STAGE_DIR/app" "$STAGE_DIR/pydeps" "$OUT_DIR"

echo "==> Building runtime staging dir: $STAGE_DIR"
echo "==> Platform: $PLATFORM_KEY"
echo "==> Version: $VERSION"

# 1) Copy Node.js CLI (compiled TypeScript from npx/dist/)
echo "==> Building npx package"
(cd "$ROOT_DIR/npx" && npm install && npm run build)

echo "==> Copying Node.js CLI"
cp -R "$ROOT_DIR/npx/dist" "$STAGE_DIR/app/"
cp "$ROOT_DIR/npx/package.json" "$STAGE_DIR/app/"

# Copy node_modules (npm dependencies like chalk, ora, commander, inquirer)
# Install only production dependencies for the runtime
echo "==> Installing Node.js runtime dependencies"
(cd "$STAGE_DIR/app" && npm install --production --no-save)

# 2) Copy python CLI app code (npx/python/cli/ and npx/python/cr/)
echo "==> Copying python CLI sources"
mkdir -p "$STAGE_DIR/app/python"
cp -R "$ROOT_DIR/npx/python/cli" "$STAGE_DIR/app/python/"
cp -R "$ROOT_DIR/npx/python/cr" "$STAGE_DIR/app/python/"
# Copy pyproject.toml so package detection works
cp "$ROOT_DIR/npx/python/pyproject.toml" "$STAGE_DIR/app/python/"

# 3) Install python deps into pydeps (no venv)
echo "==> Installing python deps into pydeps/ (no venv)"
# Find a working system python with pip (avoid venv issues)
SYS_PYTHON=""
for py in /opt/homebrew/opt/python@3.12/bin/python3.12 /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  if [ -x "$py" ] && "$py" -m pip --version >/dev/null 2>&1; then
    SYS_PYTHON="$py"
    break
  fi
done
if [ -z "$SYS_PYTHON" ]; then
  echo "ERROR: No system python with pip found" >&2
  exit 1
fi
echo "==> Using Python: $SYS_PYTHON"
# Create a temporary requirements file pointing to the python package
cat > "$STAGE_DIR/pydeps_install.txt" <<EOF
dspy>=2.6.27,<3.0.0
rich>=13.0.0
python-dotenv>=1.0.0
httpx>=0.28.1
EOF
"$SYS_PYTHON" -m pip install --break-system-packages --target "$STAGE_DIR/pydeps" -r "$STAGE_DIR/pydeps_install.txt"
rm "$STAGE_DIR/pydeps_install.txt"

# 4) Download and bundle Deno (no runtime install scripts)
echo "==> Downloading deno binary"
DENO_VERSION="2.6.6" # Latest stable, supports lockfile v5

# Map our simple platform-arch to Deno's naming convention
case "${PLATFORM}-${ARCH}" in
  darwin-arm64) DENO_PLATFORM="aarch64-apple-darwin" ;;
  darwin-x64)   DENO_PLATFORM="x86_64-apple-darwin" ;;
  linux-arm64)  DENO_PLATFORM="aarch64-unknown-linux-gnu" ;;
  linux-x64)    DENO_PLATFORM="x86_64-unknown-linux-gnu" ;;
  *) echo "Unsupported platform-arch: ${PLATFORM}-${ARCH}" >&2; exit 1 ;;
esac

DENO_ZIP="deno-${DENO_PLATFORM}.zip"
DENO_URL="https://github.com/denoland/deno/releases/download/v${DENO_VERSION}/${DENO_ZIP}"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

curl -fsSL "$DENO_URL" -o "$TMP_DIR/$DENO_ZIP"
( cd "$TMP_DIR" && unzip -q "$DENO_ZIP" )
mv "$TMP_DIR/deno" "$STAGE_DIR/bin/deno"
chmod +x "$STAGE_DIR/bin/deno"

# 5) Write entrypoint bin/asyncreview
echo "==> Writing bin/asyncreview"
cat > "$STAGE_DIR/bin/asyncreview" <<'SH'
#!/usr/bin/env sh
set -eu

RUNTIME_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

# Add Deno to PATH
export PATH="$RUNTIME_ROOT/bin:$PATH"

# Set up Python environment for when Node.js calls it
export PYTHONPATH="$RUNTIME_ROOT/pydeps:$RUNTIME_ROOT/app/python"
export DENO_DIR="${DENO_DIR:-$RUNTIME_ROOT/.deno_cache}"

# Run the Node.js CLI (which handles API keys, UI, and calls Python)
exec node "$RUNTIME_ROOT/app/dist/index.js" "$@"
SH
chmod +x "$STAGE_DIR/bin/asyncreview"

# 6) Write runtime manifest
echo "==> Writing manifest.json"
cat > "$STAGE_DIR/manifest.json" <<JSON
{
  "version": "${VERSION}",
  "platform": "${PLATFORM_KEY}",
  "built_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
}
JSON

# 7) Pack tarball
ARTIFACT="$OUT_DIR/asyncreview-runtime-v${VERSION}-${PLATFORM_KEY}.tar.gz"
echo "==> Packing runtime artifact: $ARTIFACT"
tar -C "$STAGE_DIR" -czf "$ARTIFACT" .

# 8) Print sha256 for future verification
echo "==> SHA256:"
if command -v shasum >/dev/null 2>&1; then
  shasum -a 256 "$ARTIFACT"
else
  sha256sum "$ARTIFACT"
fi

echo "==> Done."
echo "==> Artifact: $ARTIFACT"
