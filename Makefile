# Convenience commands. Run `make help` to list them.

.PHONY: help venv install run eval health clean

help:
	@echo "make venv     - create a virtual environment in .venv"
	@echo "make install  - install dependencies into the active environment"
	@echo "make run      - start the FastAPI server (http://localhost:8000)"
	@echo "make eval     - run the evaluation harness (fabrication failures must be 0)"
	@echo "make health   - curl the /health endpoint"
	@echo "make clean    - remove caches and __pycache__"

venv:
	python -m venv .venv
	@echo "Activate it with:  source .venv/bin/activate   (Windows: .venv\\Scripts\\activate)"

install:
	pip install -r requirements.txt

run:
	uvicorn main:app --reload

eval:
	python eval.py

health:
	curl -s http://localhost:8000/health

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache .mypy_cache
