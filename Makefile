.PHONY: format

STYLE_DIRS := $(pwd)

format:
	@echo "============================== Ruff formatting ====================="
	ruff format $(STYLE_DIRS)
