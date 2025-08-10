.PHONY: format test unit-test playwright-test dev-setup test-server clean-venv make-venv clear-data

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
	playwright install

format:
	uv run ruff format $(STYLE_DIRS)

unit-test:
	uv run python -m pytest tests/ -v --tb=short -m "not playwright"
	uv run python -m trinetra.database tests/test_data/config.yaml test.db
# 	rm test.db test.log

playwright-test:
	bash run.sh .venv/bin/python config_dev.yaml & \
	APP_PID=$$!; \
	sleep 5; \
	uv run python -m pytest tests/ -v --tb=short -m "playwright" --html=report.html --self-contained-html; \
	TEST_EXIT=$$?; \
	kill $$APP_PID; \
	exit $$TEST_EXIT

test: unit-test playwright-test

test-server:
	@bash scripts/test_server.sh

clear-data:
	rm trinetra.db trinetra.log test.log test.db

# Run all tasks
.PHONY: all
all: format test test-server
	@echo "All tasks completed!"