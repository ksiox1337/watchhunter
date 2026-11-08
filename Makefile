.PHONY: install install-dev lint fmt typecheck test test-unit test-integration start run clean

# Prefer the project virtualenv if present, otherwise fall back to python3.
VENV := .venv
PYTHON := $(shell [ -x $(VENV)/bin/python ] && echo $(VENV)/bin/python || echo python3)

install:
	$(PYTHON) -m pip install -e .

install-dev:
	$(PYTHON) -m pip install -e . -r requirements-dev.txt

lint:
	$(PYTHON) -m ruff check src tests

fmt:
	$(PYTHON) -m ruff format src tests
	$(PYTHON) -m ruff check --fix src tests

typecheck:
	$(PYTHON) -m mypy

test:
	$(PYTHON) -m pytest

test-unit:
	$(PYTHON) -m pytest tests/unit

test-integration:
	$(PYTHON) -m pytest tests/integration

start run:
	$(PYTHON) -m watchhunter

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -name "*.pyc" -delete
