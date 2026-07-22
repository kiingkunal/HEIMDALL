# HEIMDALL — dev commands. SQLite + parquet, no cloud. Runs offline on the replay dataset.
PY := .venv/bin/python
PIP := .venv/bin/pip

.PHONY: help venv install dev harvest harvest-prices harvest-news harvest-sanctions \
        replay-walk test resilience replay-build replay-lock backtest clean

help:
	@echo "HEIMDALL make targets:"
	@echo "  install         venv + deps"
	@echo "  dev             run FastAPI backend (uvicorn, reload) on :8100"
	@echo "  harvest         run all live harvesters once"
	@echo "  harvest-prices  EIA Brent (authoritative) + yfinance display"
	@echo "  harvest-news    GDELT DOC live monitoring lane (rate-limited, spaced)"
	@echo "  harvest-sanctions  OFAC SDN download"
	@echo "  replay-walk     stream the 2025 replay chronologically (leakage-guarded)"
	@echo "  test            pytest suite"
	@echo "  replay-build    validate the immutable sourced 2025 replay dataset"
	@echo "  replay-lock     lock backtest thresholds and engine assumptions"
	@echo "  backtest        run locked leakage-guarded case study -> docs/metrics.md"
	@echo "  resilience      [Phase 3+] run the six resilience stress scenarios"

venv:
	python3.11 -m venv .venv

install: venv
	$(PIP) install -q --upgrade pip
	$(PIP) install -q fastapi uvicorn apscheduler gdeltdoc pandas pyarrow numpy \
		ortools searoute requests openai python-dotenv pytest pyyaml httpx websockets yfinance

dev:
	.venv/bin/uvicorn backend.app:app --reload --port 8100

harvest: harvest-prices harvest-sanctions harvest-news

harvest-prices:
	$(PY) -m backend.harvesters.prices

harvest-news:
	$(PY) -m backend.harvesters.news

harvest-sanctions:
	$(PY) -m backend.harvesters.sanctions

replay-walk:
	$(PY) -m backend.replay.loader

test:
	$(PY) -m pytest -q

replay-build:
	$(PY) -m backend.replay.backtest --validate

replay-lock:
	$(PY) -m backend.replay.backtest --lock

backtest:
	$(PY) -m backend.replay.backtest

resilience:
	$(PY) -m backend.engines.resilience

clean:
	rm -f backend/state.db backend/state.db-wal backend/state.db-shm
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
