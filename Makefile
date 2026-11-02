.PHONY: help install dev lint format typecheck test coverage check run docker-build docker-up docker-down clean

PYTHON ?= python
VENV ?= .venv
BIN := $(VENV)/bin

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Create a virtualenv and install production dependencies
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e .

dev: ## Install the project with development tools
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e ".[dev]"
	$(BIN)/pre-commit install

lint: ## Run ruff linting
	$(BIN)/ruff check .

format: ## Format code and auto-fix safe lint issues
	$(BIN)/ruff format .
	$(BIN)/ruff check --fix .

typecheck: ## Run mypy
	$(BIN)/mypy leetgo

test: ## Run the test suite
	$(BIN)/pytest

coverage: ## Run tests with a coverage report
	$(BIN)/pytest --cov=leetgo --cov-report=term-missing

check: lint format-check typecheck test ## Run every quality gate

format-check: ## Verify formatting without modifying files
	$(BIN)/ruff format --check .

run: ## Start the bot
	$(BIN)/python -m leetgo

docker-build: ## Build the production image
	docker build -t leetgo:local .

docker-up: ## Start with Docker Compose
	docker compose up -d --build

docker-down: ## Stop Docker Compose
	docker compose down

clean: ## Remove caches and build artefacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage dist build *.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
