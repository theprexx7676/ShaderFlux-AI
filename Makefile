.PHONY: setup lint format type test test-all check

setup:
	uv venv .venv
	uv pip install -e ".[dev]"
	.venv/bin/pre-commit install

lint:
	.venv/bin/ruff check .
	.venv/bin/ruff format --check .

format:
	.venv/bin/ruff check --fix .
	.venv/bin/ruff format .

type:
	.venv/bin/mypy

test:
	.venv/bin/pytest -m "not needs_tools and not needs_llm and not needs_gpu"

test-all:
	.venv/bin/pytest

check: lint type test
