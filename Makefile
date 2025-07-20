.PHONY: format test dev-setup test-server

STYLE_DIRS := $(pwd)

dev-setup:
	uv venv .venv
	uv pip install -e .[dev]

format:
	uv run ruff format $(STYLE_DIRS)

test:
	uv run python -m pytest tests/ -v --tb=short

test-server:
	@bash scripts/test_server.sh

# Run all tasks
.PHONY: all
all: format test test-server
	@echo "All tasks completed!"