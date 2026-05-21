.PHONY: init start-dev seed migrate clean-sessions test test-unit test-acceptance

init:
	uv sync
	docker compose up -d
	@echo "Waiting for PostgreSQL to be ready..."
	@sleep 3
	uv run alembic upgrade head
	uv run python seed.py
	@echo "✓ Project initialized. Run 'make start-dev' to launch the API."

start-dev:
	docker compose up -d
	uv run fastapi dev main.py

seed:
	uv run python seed.py

migrate:
	uv run alembic upgrade head

clean-sessions:
	uv run python clean_sessions.py

test:
	uv run pytest

test-unit:
	uv run pytest tests/test_unit.py tests/test_interview_unit.py -v

test-acceptance:
	uv run pytest tests/test_acceptance.py -v
