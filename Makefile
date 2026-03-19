.PHONY: help install install-dev test lint clean build
.DEFAULT_GOAL := help

help: ## Show available commands
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "%-20s %s\n", $$1, $$2}'

install: ## Install the package in editable mode
	python -m pip install -e .

install-dev: ## Install the package with development dependencies
	python -m pip install -e .[dev]

test: ## Run the test suite
	pytest tests/ -v

lint: ## Run a basic compile check
	python -m compileall pyautogui_mcp_server tests

build: ## Build sdist and wheel
	python -m build

clean: ## Remove build artifacts and caches
	rm -rf build dist *.egg-info .pytest_cache .coverage htmlcov .mypy_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete
