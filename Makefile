.PHONY: up down logs test backend-test frontend-test lint

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f

test: backend-test frontend-test

backend-test:
	cd backend && python -m pytest

frontend-test:
	cd frontend && npm test

lint:
	cd backend && python -m ruff check app tests
