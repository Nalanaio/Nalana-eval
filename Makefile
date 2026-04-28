.PHONY: install test lint clean fixtures \
        docker-build docker-test-unit docker-test-blender docker-smoke docker-eval

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

# ── Docker targets ──────────────────────────────────────────────────────────

docker-build:
	docker compose build

# Pure-Python unit tests (slim image, no Blender, ~20 s)
docker-test-unit:
	docker compose run --build --rm unit

# Full test suite including Blender subprocess integration tests (~2-3 min)
docker-test-blender:
	docker compose run --build --rm blender

# End-to-end smoke eval: mock model + mock Blender (no API keys needed)
docker-smoke:
	docker compose run --build --rm smoke

# Real eval run — set EVAL_MODELS / API keys in environment or .env file
docker-eval:
	docker compose run --build --rm eval
