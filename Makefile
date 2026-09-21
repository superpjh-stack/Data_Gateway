# 임진강김치 PLC 데이터수집 디지털 트윈
.PHONY: setup run run-prod test test-py test-web e2e lint build demo clean

setup:
	uv sync
	cd dashboard && (npm ci || npm install)

run:
	@echo "백엔드 http://127.0.0.1:8000 · 대시보드(dev) http://127.0.0.1:5173"
	@trap 'kill 0' INT TERM EXIT; \
	uv run python -m twin.supervisor --fresh & \
	(cd dashboard && npm run dev -- --strictPort) & \
	wait

build:
	cd dashboard && npm run build

run-prod: build
	@echo "http://127.0.0.1:8000 (대시보드 포함)"
	uv run python -m twin.supervisor --fresh

lint:
	uv run ruff check src tests scripts
	uv run ruff format --check src tests scripts
	uv run mypy --strict src/twin/plc src/twin/edge src/twin/mes

test-py:
	uv run pytest --cov=twin --cov-report=term-missing:skip-covered -q

test-web:
	cd dashboard && npm test

e2e: build
	cd dashboard && npx playwright test

test: lint test-py test-web

demo: build
	uv run python scripts/demo.py

clean:
	rm -rf data dashboard/dist .pytest_cache .coverage
