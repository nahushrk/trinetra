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
	@echo "============================== Testing server startup ====================="
	@echo "Testing server startup with current Python runtime and dev config..."
	@bash run.sh $(shell which python) config_dev.yaml & \
		SERVER_PID=$$!; \
		sleep 5; \
		if ps -p $$SERVER_PID > /dev/null; then \
			echo "✓ Server started successfully"; \
			kill $$SERVER_PID; \
			sleep 2; \
			echo "✓ Server stopped cleanly"; \
		else \
			echo "✗ Server failed to start"; \
			exit 1; \
		fi

# Run all tasks
.PHONY: all
all: format test test-server
	@echo "All tasks completed!"