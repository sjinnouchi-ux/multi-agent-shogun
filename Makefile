.PHONY: test test-no-skip build lint check help install-deps clean skill-registry-check skill-registry-lock

GENERATED_OUTPUTS := instructions/generated/ .opencode/agents/ \
	instructions/shogun.md instructions/karo.md instructions/ashigaru.md \
	instructions/gunshi.md instructions/oometsuke.md AGENTS.md \
	.github/copilot-instructions.md agents/default/system.md agents/default/agent.yaml

# Default target
help:
	@echo "Multi-CLI Shogun - Development Commands"
	@echo ""
	@echo "Available targets:"
	@echo "  make test          - Run bats unit tests"
	@echo "  make test-no-skip  - Deployment-host tests; any skip or missing prerequisite fails"
	@echo "  make test-int      - Run bats integration tests"
	@echo "  make build         - Run build_instructions.sh"
	@echo "  make lint          - Run shellcheck on lib/ and scripts/"
	@echo "  make check         - Run build + diff check (CI equivalent)"
	@echo "  make skill-registry-check - Validate the registry and tracked lock"
	@echo "  make skill-registry-lock  - Regenerate the deterministic registry lock"
	@echo "  make install-deps  - Install test dependencies (bats, helpers)"
	@echo "  make clean         - Clean test artifacts"
	@echo ""

# Run unit tests
test:
	@echo "Running unit tests..."
	@if ! command -v bats >/dev/null 2>&1; then \
		echo "ERROR: bats not installed. Run 'make install-deps' first."; \
		exit 1; \
	fi
	@if ls tests/*.bats 1>/dev/null 2>&1; then \
		echo "--- Root-level tests ---"; \
		bats tests/*.bats --timing; \
	fi
	@if [ -d tests/unit ] && ls tests/unit/*.bats 1>/dev/null 2>&1; then \
		echo "--- Unit tests ---"; \
		bats tests/unit/ --timing; \
	fi

test-no-skip:
	@set -eu; \
	for cmd in bats python3 tmux claude; do \
		command -v "$$cmd" >/dev/null 2>&1 || { \
			echo "ERROR: missing required command: $$cmd"; exit 1; \
		}; \
	done; \
	python3 -c 'import sys; assert sys.version_info >= (3, 10)' || { echo "ERROR: Python 3.10+ required"; exit 1; }; \
	test -x .venv/bin/python3 || { echo "ERROR: .venv/bin/python3 missing"; exit 1; }; \
	.venv/bin/python3 -c 'import yaml' || { echo "ERROR: PyYAML missing"; exit 1; }; \
	test -f tests/test_helper/bats-support/load.bash || { echo "ERROR: bats-support missing"; exit 1; }; \
	test -f tests/test_helper/bats-assert/load.bash || { echo "ERROR: bats-assert missing"; exit 1; }; \
	tap="$$(mktemp)"; \
	trap 'rm -f "$$tap"' EXIT; \
	set +e; \
	bats --formatter tap tests/*.bats tests/unit/ \
		tests/integration/test_codex_diagnostics_tmux.bats >"$$tap" 2>&1; \
	rc="$$?"; \
	set -e; \
	cat "$$tap"; \
	tests="$$(grep -Ec '^(ok|not ok) ' "$$tap" || true)"; \
	skips="$$(grep -Eic '^ok [0-9]+ .*# skip([[:space:]]|$$)' "$$tap" || true)"; \
	echo "tests=$$tests skips=$$skips exit=$$rc"; \
	test "$$tests" -gt 0; \
	test "$$rc" -eq 0; \
	test "$$skips" -eq 0

# Run integration tests
test-int:
	@echo "Running integration tests (Claude only)..."
	@if [ ! -d tests/integration ]; then \
		echo "ERROR: tests/integration directory not found"; \
		exit 1; \
	fi
	@if ! command -v bats >/dev/null 2>&1; then \
		echo "ERROR: bats not installed. Run 'make install-deps' first."; \
		exit 1; \
	fi
	bats tests/integration/ --filter-tags '!copilot,!codex' --timing

# Run all tests
test-all: test test-int

# Build instructions (Phase 2 feature)
build:
	@echo "Building instruction files..."
	@if [ -f scripts/build_instructions.sh ]; then \
		bash scripts/build_instructions.sh; \
	else \
		echo "WARNING: scripts/build_instructions.sh not found"; \
		echo "This will be available in Phase 2 (template generation)"; \
	fi

# Validate canonical skills and confirm the tracked deterministic lock.
skill-registry-check:
	@bash scripts/skill_registry.sh check

# Maintainer-only regeneration after reviewed registry or skill changes.
skill-registry-lock:
	@bash scripts/skill_registry.sh lock

# Run shellcheck linter
lint:
	@echo "Running shellcheck..."
	@if ! command -v shellcheck >/dev/null 2>&1; then \
		echo "ERROR: shellcheck not installed"; \
		echo "Install: sudo apt-get install shellcheck (Linux) or brew install shellcheck (Mac)"; \
		exit 1; \
	fi
	@echo "Checking lib/..."
	@if [ -d lib ]; then \
		find lib -name '*.sh' -type f -exec shellcheck {} \; ; \
	fi
	@echo "Checking scripts/..."
	@if [ -d scripts ]; then \
		find scripts -name '*.sh' -type f -exec shellcheck {} \; ; \
	fi
	@echo "✓ Shellcheck passed"

# Build + diff check (CI equivalent)
check: build
	@echo "Checking for uncommitted instruction changes..."
	@if [ -f scripts/build_instructions.sh ] && [ -d instructions/generated ] && [ -d .opencode/agents ]; then \
		untracked="$$(git ls-files --others --exclude-standard -- $(GENERATED_OUTPUTS))"; \
		if [ -n "$$untracked" ]; then \
			echo "ERROR: Generated instruction outputs are untracked:"; \
			echo "$$untracked"; \
			exit 1; \
		elif git diff --exit-code -- $(GENERATED_OUTPUTS); then \
			echo "✓ Generated instructions and OpenCode agents are in sync"; \
		else \
			echo "ERROR: Generated instructions or OpenCode agents are out of sync!"; \
			echo "Run 'make build' and commit the changes."; \
			exit 1; \
		fi; \
	else \
		echo "WARNING: build_instructions.sh, instructions/generated, or .opencode/agents not found"; \
		echo "Skipping diff check (Phase 2 feature)"; \
	fi

# Install test dependencies
install-deps:
	@echo "Installing test dependencies..."
	@echo "1. Installing bats-core..."
	@if command -v npm >/dev/null 2>&1; then \
		npm install -g bats; \
	else \
		echo "ERROR: npm not found. Install Node.js first."; \
		echo "Alternatively: brew install bats-core (Mac) or apt-get install bats (Linux)"; \
		exit 1; \
	fi
	@echo "2. Setting up bats helpers..."
	@mkdir -p tests/test_helper
	@if [ ! -d tests/test_helper/bats-support ]; then \
		git clone --depth 1 https://github.com/bats-core/bats-support tests/test_helper/bats-support; \
	fi
	@if [ ! -d tests/test_helper/bats-assert ]; then \
		git clone --depth 1 https://github.com/bats-core/bats-assert tests/test_helper/bats-assert; \
	fi
	@echo "3. Checking venv + PyYAML..."
	@if [ ! -f .venv/bin/python3 ]; then \
		echo "WARNING: .venv not found. Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"; \
	elif ! .venv/bin/python3 -c "import yaml" 2>/dev/null; then \
		echo "WARNING: PyYAML not in venv. Run: .venv/bin/pip install -r requirements.txt"; \
	fi
	@echo "✓ Dependencies installed"

# Clean test artifacts
clean:
	@echo "Cleaning test artifacts..."
	@find tests -name '*.tap' -type f -delete 2>/dev/null || true
	@echo "✓ Cleaned"

# Quick development workflow
dev: lint test
	@echo "✓ Development checks passed"
