.PHONY: format test dev-setup test-server clean-venv make-venv clear-data

STYLE_DIRS := $(pwd)

make-venv:
	uv venv .venv --python=python3.10
	@echo "Virtual environment created with Python 3.10"

clean-venv:
	rm -rf .venv
	uv venv .venv --python=python3.10
	@echo "Virtual environment recreated with Python 3.10"

dev-setup: clean-venv
	uv pip install -e .[dev]

format:
	uv run ruff format $(STYLE_DIRS)

test:
	uv run python -m pytest tests/ -v --tb=short
	uv run python -m trinetra.database tests/test_data/config.yaml test.db

test-server:
	@bash scripts/test_server.sh

clear-data:
	rm trinetra.db trinetra.log test.log test.db

# Run all tasks
.PHONY: all
all: format test test-server
	@echo "All tasks completed!"