# AsyncReview Runtime Build System
# 
# Usage:
#   make build          - Build the runtime for current platform
#   make install        - Install the built runtime locally
#   make test           - Run the bundled runtime test
#   make publish        - Publish to GitHub Releases
#   make all            - Build, install, and test
#   make clean          - Clean build artifacts
#
# Docker Usage:
#   make docker-up      - Run production environment (User mode)
#   make docker-dev     - Run development environment (Hot-reload)
#
# Version Management:
#   make bump-patch     - Bump patch version (0.5.0 -> 0.5.1)
#   make bump-minor     - Bump minor version (0.5.0 -> 0.6.0)
#   make bump-major     - Bump major version (0.5.0 -> 1.0.0)

.PHONY: all build install test publish clean bump-patch bump-minor bump-major version docker-up docker-dev

# Version file - single source of truth
VERSION_FILE := VERSION
VERSION := $(shell cat $(VERSION_FILE) 2>/dev/null || echo "0.5.0")

# Platform detection
UNAME_S := $(shell uname -s | tr '[:upper:]' '[:lower:]')
UNAME_M := $(shell uname -m)
ifeq ($(UNAME_M),arm64)
  ARCH := arm64
else ifeq ($(UNAME_M),aarch64)
  ARCH := arm64
else
  ARCH := x64
endif
PLATFORM := $(UNAME_S)-$(ARCH)

# Paths
DIST_DIR := dist
RUNTIME_ARTIFACT := $(DIST_DIR)/asyncreview-runtime-v$(VERSION)-$(PLATFORM).tar.gz

# Default target
all: build install test

# Ensure VERSION file exists
$(VERSION_FILE):
	@echo "0.5.0" > $(VERSION_FILE)

# Show current version
version: $(VERSION_FILE)
	@echo "Current version: $(VERSION)"
	@echo "Platform: $(PLATFORM)"
	@echo "Artifact: $(RUNTIME_ARTIFACT)"

# Build the runtime
build: $(VERSION_FILE)
	@echo "==> Building AsyncReview v$(VERSION) for $(PLATFORM)"
	@./scripts/build_runtime_local.sh $(VERSION)

# Install the built runtime locally
install: $(RUNTIME_ARTIFACT)
	@echo "==> Installing v$(VERSION)"
	@./scripts/install_runtime_local.sh $(RUNTIME_ARTIFACT) $(VERSION)

# Test the installed runtime
test:
	@echo "==> Testing v$(VERSION)"
	@./scripts/run_cached.sh $(VERSION) review \
		--url https://github.com/stanfordnlp/dspy/pull/9240 \
		-q "Use SEARCH_CODE to find process_pair"

# Quick build+install+test cycle
quick: build install test

# Clean build artifacts
clean:
	@echo "==> Cleaning build artifacts"
	@rm -rf $(DIST_DIR)/*.tar.gz
	@rm -rf .runtime_stage
	@echo "Done."

# ============================================================
# Docker Helpers
# ============================================================

docker-up:
	@if [ ! -f .env ]; then echo "Error: .env file not found. Copy .env.example to .env and fill in API keys."; exit 1; fi
	@echo "==> Starting AsyncReview in Production Mode (Immutable)..."
	@docker compose up --build

docker-dev:
	@if [ ! -f .env ]; then echo "Error: .env file not found. Copy .env.example to .env and fill in API keys."; exit 1; fi
	@echo "==> Starting AsyncReview in Development Mode (Hot-Reload)..."
	@docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

# ============================================================
# Version Management
# ============================================================

bump-patch: $(VERSION_FILE)
	@echo "$(VERSION)" | awk -F. '{printf "%d.%d.%d\n", $$1, $$2, $$3+1}' > $(VERSION_FILE)
	@echo "Bumped to $$(cat $(VERSION_FILE))"

bump-minor: $(VERSION_FILE)
	@echo "$(VERSION)" | awk -F. '{printf "%d.%d.0\n", $$1, $$2+1}' > $(VERSION_FILE)
	@echo "Bumped to $$(cat $(VERSION_FILE))"

bump-major: $(VERSION_FILE)
	@echo "$(VERSION)" | awk -F. '{printf "%d.0.0\n", $$1+1}' > $(VERSION_FILE)
	@echo "Bumped to $$(cat $(VERSION_FILE))"

# ============================================================
# Publishing to GitHub Releases
# ============================================================

# Check if gh CLI is available and authenticated
.PHONY: check-gh
check-gh:
	@command -v gh >/dev/null 2>&1 || { echo "Error: gh CLI not installed"; exit 1; }
	@gh auth status >/dev/null 2>&1 || { echo "Error: gh not authenticated. Run: gh auth login"; exit 1; }

# Create a GitHub release with the runtime artifact
publish: check-gh $(RUNTIME_ARTIFACT)
	@echo "==> Publishing v$(VERSION) to GitHub Releases"
	@echo "    Artifact: $(RUNTIME_ARTIFACT)"
	@gh release create v$(VERSION) \
		--title "AsyncReview v$(VERSION)" \
		--notes "Runtime release for $(PLATFORM)" \
		$(RUNTIME_ARTIFACT) \
		|| { echo "Release v$(VERSION) may already exist. Use 'make publish-update' to add artifacts."; exit 1; }
	@echo "==> Published: https://github.com/AsyncFuncAI/AsyncReview/releases/tag/v$(VERSION)"

# Add artifact to existing release (for multi-platform builds)
publish-update: check-gh $(RUNTIME_ARTIFACT)
	@echo "==> Adding $(PLATFORM) artifact to v$(VERSION) release"
	@gh release upload v$(VERSION) $(RUNTIME_ARTIFACT) --clobber
	@echo "==> Updated: https://github.com/AsyncFuncAI/AsyncReview/releases/tag/v$(VERSION)"

# ============================================================
# Development Helpers
# ============================================================

# Build npx package only (for dev iteration)
build-npx:
	@cd npx && npm install && npm run build

# Run local dev mode (not bundled)
dev:
	@cd npx && node dist/index.js review --url $(URL) -q "$(Q)"

# ============================================================
# Release Workflow
# ============================================================

# Full release: bump, commit, tag, push (triggers CI/CD for runtime builds)
release-patch: bump-patch release-commit
release-minor: bump-minor release-commit
release-major: bump-major release-commit

release-commit: $(VERSION_FILE)
	@echo "==> Creating release v$$(cat $(VERSION_FILE))"
	@git add VERSION npx/package.json
	@git commit -m "Release v$$(cat $(VERSION_FILE))"
	@git tag v$$(cat $(VERSION_FILE))
	@echo "==> Pushing to trigger CI/CD..."
	@git push origin main --tags
	@echo "==> Release v$$(cat $(VERSION_FILE)) triggered!"
	@echo "    Monitor: https://github.com/AsyncFuncAI/AsyncReview/actions"
	@echo ""
	@echo "    After CI/CD completes, run: make publish-npm"

# ============================================================
# npm Publishing (Local Control)
# ============================================================

# Publish thin wrapper to npm (run this locally after CI/CD completes)
publish-npm: $(VERSION_FILE)
	@echo "==> Publishing asyncreview@$(VERSION) to npm"
	@cd npx && npm version $(VERSION) --no-git-tag-version --allow-same-version
	@cd npx && npm run build
	@echo "==> Dry run first..."
	@cd npx && npm publish --dry-run
	@echo ""
	@read -p "Publish to npm? [y/N] " confirm && [ "$$confirm" = "y" ] || exit 1
	@cd npx && npm publish --access public
	@echo "==> Published: https://www.npmjs.com/package/asyncreview"

# Show help
help:
	@echo "AsyncReview Runtime Build System"
	@echo ""
	@echo "Docker Commands (Preferred):"
	@echo "  make docker-up    - Run production environment (User mode)"
	@echo "  make docker-dev   - Run development environment (Hot-reload)"
	@echo ""
	@echo "Build Commands:"
	@echo "  make build        - Build runtime v$(VERSION) for $(PLATFORM)"
	@echo "  make install      - Install built runtime locally"
	@echo "  make test         - Test installed runtime"
	@echo "  make quick        - Build + install + test"
	@echo "  make clean        - Remove build artifacts"
	@echo ""
	@echo "Version Commands:"
	@echo "  make version      - Show current version"
	@echo "  make bump-patch   - Bump patch ($(VERSION) -> next patch)"
	@echo "  make bump-minor   - Bump minor version"
	@echo "  make bump-major   - Bump major version"
	@echo ""
	@echo "Release Commands:"
	@echo "  make release-patch - Bump, commit, tag, push (triggers CI/CD)"
	@echo "  make release-minor - Bump minor, triggers CI/CD"
	@echo "  make release-major - Bump major, triggers CI/CD"
	@echo "  make publish-npm   - Publish thin wrapper to npm (local)"
	@echo ""
	@echo "Manual GitHub Release Commands:"
	@echo "  make publish      - Create GitHub release with local artifact"
	@echo "  make publish-update - Add artifact to existing release"
	@echo ""
	@echo "Dev Commands:"
	@echo "  make build-npx    - Build TypeScript only"
	@echo "  make dev URL=... Q=... - Run dev mode"
