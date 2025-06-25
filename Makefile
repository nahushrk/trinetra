.PHONY: format

STYLE_DIRS := $(pwd)

format:
	@echo "============================== Ruff formatting ====================="
	ruff format $(STYLE_DIRS)

# Run all tasks
.PHONY: all
all: format
	@echo "All tasks completed!"