.PHONY: format test dev-setup test-server

STYLE_DIRS := $(pwd)

dev-setup:
	@echo "============================== Setting up development environment ====================="
	pip install .[dev]

format:
	@echo "============================== Ruff formatting ====================="
	ruff format $(STYLE_DIRS)

test:
	@echo "============================== Running tests ====================="
	python -m pytest tests/ -v --tb=short

test-server:
	@bash scripts/test_server.sh

# Run all tasks
.PHONY: all
all: format test test-server
	@echo "All tasks completed!"