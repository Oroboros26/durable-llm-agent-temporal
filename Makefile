install:
	pip install -e ".[dev]"

seed:
	python -c "from durable_agent import tools; tools.seed()"

worker:
	python -m durable_agent.worker

run:
	docker compose up -d

test:
	ruff check src tests && pytest -q tests/test_idempotency.py tests/test_workflow.py

chaos:
	python tests/chaos.py --kills 3 --seed 42
