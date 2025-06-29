.PHONY: format test dev-setup

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

# Run all tasks
.PHONY: all
all: format test
	@echo "All tasks completed!"