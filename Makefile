.PHONY: install test lint clean fixtures docker-run bench

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

# ── Docker ──────────────────────────────────────────────────────────────────
# Run all test cases end-to-end in headless Blender.
# Configure via env vars — no file edits needed:
#   MODELS   model IDs (default: mock)
#   CASES    number of cases, 0=all (default: 0)
#   SUITE    fixture path (default: fixtures/starter_v3)
#   ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY
bench:
	python bench.py

docker-run:
	docker compose run --build --rm eval
