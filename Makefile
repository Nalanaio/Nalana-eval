.PHONY: install test lint clean fixtures

install:
	pip install -e ".[dev]"

test:
	python -m pytest tests/ -v

lint:
	python -m ruff check nalana_eval/ tests/ || true
	python -m mypy nalana_eval/ --ignore-missing-imports || true

fixtures:
	python fixtures/synthetic/generate_cases.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache dist build nalana_eval.egg-info
